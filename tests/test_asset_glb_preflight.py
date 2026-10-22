from __future__ import annotations

import copy
import importlib
import json
import struct

import pytest


def triangle():
    binary = struct.pack('<9f3H', 0., 0., 0., 1., 0., 0., 0., 1., 0., 0, 1, 2)
    return {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [{'buffer': 0, 'byteLength': 36}, {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'},
                      {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}]}, binary


def glb(manifest, binary, raw_json=None):
    text = json.dumps(manifest, separators=(',', ':')).encode() if raw_json is None else raw_json
    text += b' '*(-len(text) % 4)
    binary += b'\0'*(-len(binary) % 4)
    return b'glTF'+struct.pack('<II', 2, 28+len(text)+len(binary))+struct.pack('<II', len(text), 0x4e4f534a)+text+struct.pack('<II', len(binary), 0x004e4942)+binary


@pytest.fixture
def module(addon_package):
    return importlib.import_module(addon_package+'.asset_glb_preflight')


def test_complete_core_static_glb_preflight_without_blender(module):
    manifest, binary = triangle()
    result = module.preflight_glb(glb(manifest, binary))
    assert result['objects'] == 1 and result['vertices'] == 3 and result['triangles'] == 1
    assert result['dependencies'] == [] and result['self_contained']
    assert not result['animation_present'] and result['instance_vertices'] == 3


@pytest.mark.parametrize('mutation', ['uri', 'data_uri', 'extensions', 'extras', 'animations', 'skins', 'camera',
    'sparse', 'normalized', 'colors', 'normal_texture', 'roughness_texture'])
def test_unreviewed_fields_and_external_loads_fail_closed(module, mutation):
    manifest, binary = triangle()
    if mutation in ('uri', 'data_uri'):
        manifest['buffers'][0]['uri'] = '../secret.bin' if mutation == 'uri' else 'data:application/octet-stream;base64,AAAA'
    elif mutation in ('extensions', 'extras', 'animations', 'skins'):
        manifest[mutation] = [] if mutation in ('animations', 'skins') else {}
    elif mutation == 'camera':
        manifest['nodes'][0]['camera'] = 0
    elif mutation in ('sparse', 'normalized'):
        manifest['accessors'][0][mutation] = {} if mutation == 'sparse' else True
    elif mutation == 'colors':
        manifest['meshes'][0]['primitives'][0]['attributes']['COLOR_0'] = 0
    else:
        manifest['materials'] = [{'normalTexture': {'index': 0}}] if mutation == 'normal_texture' else [{'pbrMetallicRoughness': {'metallicRoughnessTexture': {'index': 0}}}]
    with pytest.raises(module.BridgeError):
        module.preflight_glb(glb(manifest, binary))


@pytest.mark.parametrize('mutation', ['envelope', 'tail', 'missing_bin', 'duplicate_keys', 'nan', 'indices', 'stride', 'bounds',
    'cycle', 'double_parent', 'unreachable', 'children_object', 'bool_index', 'alpha_cutoff', 'negative_color', 'quaternion', 'instance_budget'])
def test_malformed_or_overbudget_glb_rejected(module, mutation):
    manifest, binary = triangle()
    raw_json = None
    if mutation == 'duplicate_keys':
        raw_json = b'{"asset":{"version":"2.0"},"asset":{"version":"2.0"}}'
    elif mutation == 'nan':
        binary = struct.pack('<f', float('nan'))+binary[4:]
    elif mutation == 'indices':
        binary = binary[:-2]+struct.pack('<H', 3)
    elif mutation == 'stride':
        manifest['bufferViews'][0]['byteStride'] = 8
    elif mutation == 'bounds':
        manifest['accessors'][0]['count'] = 4
    elif mutation == 'cycle':
        manifest['nodes'][0]['children'] = [0]
    elif mutation == 'double_parent':
        manifest['nodes'].append({'children': [0]})
        manifest['scenes'][0]['nodes'] = [0, 1]
    elif mutation == 'unreachable':
        manifest['nodes'].append({})
    elif mutation == 'children_object':
        manifest['nodes'][0]['children'] = [{}]
    elif mutation == 'bool_index':
        manifest['bufferViews'][0]['buffer'] = False
    elif mutation in ('alpha_cutoff', 'negative_color'):
        manifest['materials'] = [{'alphaCutoff': float('nan')}] if mutation == 'alpha_cutoff' else [{'pbrMetallicRoughness': {'baseColorFactor': [-.1, 1., 1., 1.]}}]
    elif mutation == 'quaternion':
        manifest['nodes'][0]['rotation'] = [0., 0., 0., 0.]
    elif mutation == 'instance_budget':
        manifest['nodes'] = [{'mesh': 0} for _ in range(64)]
        manifest['scenes'][0]['nodes'] = list(range(64))
        manifest['accessors'][0]['count'] = 1800
        binary = struct.pack('<9f', *([0.]*9))*600 + binary[-6:]
        manifest['buffers'][0]['byteLength'] = len(binary)
        manifest['bufferViews'][0]['byteLength'] = len(binary)-6
        manifest['bufferViews'][1]['byteOffset'] = len(binary)-6
    payload = glb(manifest, binary, raw_json)
    if mutation == 'envelope':
        payload = b'bad!'+payload[4:]
    elif mutation == 'tail':
        payload += b'tail'
    elif mutation == 'missing_bin':
        payload = payload[:-8]
    with pytest.raises(module.BridgeError):
        module.preflight_glb(payload)


def test_preflight_checks_cancellation_and_revalidates_binary_bytes(module):
    manifest, binary = triangle()
    calls = []
    result = module.preflight_glb(glb(copy.deepcopy(manifest), binary), check=lambda: calls.append(True))
    assert result['self_contained'] and calls
    def cancelled():
        raise RuntimeError('canceled')
    with pytest.raises(RuntimeError, match='canceled'):
        module.preflight_glb(glb(manifest, binary), check=cancelled)


def test_reused_primitive_budget_rejects_before_rewalking_binary_accessors(module, monkeypatch):
    manifest, binary = triangle()
    primitive = manifest['meshes'][0]['primitives'][0]
    manifest['meshes'][0]['primitives'] = [primitive, copy.deepcopy(primitive)]
    monkeypatch.setattr(module, 'MAX_VERTICES', 5)
    original = module.struct.unpack_from
    position_reads = []
    def counted(layout, *args):
        if layout == '<fff':
            position_reads.append(True)
        return original(layout, *args)
    monkeypatch.setattr(module.struct, 'unpack_from', counted)
    with pytest.raises(module.BridgeError, match='vertex budget'):
        module.preflight_glb(glb(manifest, binary))
    # Three rows in the complete unreferenced-accessor validation, then three
    # in the first primitive. The over-budget primitive performs no array walk.
    assert len(position_reads) == 6


def test_aggregate_triangle_budget_is_checked_per_primitive(module, monkeypatch):
    manifest, binary = triangle()
    primitive = manifest['meshes'][0]['primitives'][0]
    manifest['meshes'][0]['primitives'] = [primitive, copy.deepcopy(primitive)]
    monkeypatch.setattr(module, 'MAX_TRIANGLES', 1)
    with pytest.raises(module.BridgeError, match='triangle budget'):
        module.preflight_glb(glb(manifest, binary))


@pytest.mark.parametrize('kind', ['projective', 'shear', 'hierarchy_overflow'])
def test_transform_admission_rejects_native_decomposition_and_accumulation_losses(module, kind):
    manifest, binary = triangle()
    if kind == 'hierarchy_overflow':
        manifest['nodes'] = [{'scale': [1e6, 1e6, 1e6], 'children': [1]},
                             {'mesh': 0, 'scale': [1e6, 1e6, 1e6]}]
    else:
        matrix = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
        matrix[3 if kind == 'projective' else 4] = .5
        manifest['nodes'][0]['matrix'] = matrix
    with pytest.raises(module.BridgeError):
        module.preflight_glb(glb(manifest, binary))


def test_affine_rotated_scaled_matrix_and_nested_trs_are_admitted(module):
    manifest, binary = triangle()
    manifest['nodes'] = [
        {'matrix': [0., 3., 0., 0., -2., 0., 0., 0., 0., 0., 4., 0., 4., 5., 6., 1.], 'children': [1]},
        {'mesh': 0, 'translation': [1., -2., 3.], 'rotation': [0., 0., 1., 0.], 'scale': [-1., 2., 0.]},
    ]
    assert module.preflight_glb(glb(manifest, binary))['objects'] == 2
