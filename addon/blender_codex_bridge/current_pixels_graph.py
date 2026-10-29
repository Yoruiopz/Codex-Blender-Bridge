# SPDX-License-Identifier: GPL-3.0-or-later
"""Finite loaded-Image and authored consumer graph observations.

No bpy import, filesystem probe, scene synchronization, mutation or implicit
decode occurs here. Catalog pins must come from independently reviewed official
build metadata. A census is observation, never permission or self-qualification.
Initial complete capture follows current grants and resource/path preflight;
the pre-grant identity witness deliberately makes no pixel-change guarantee.
Native arrays/bytes stay in active payload preparation, never plain summaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import threading
from array import array
from collections.abc import Callable, Generator
from dataclasses import dataclass
from inspect import getattr_static
from itertools import islice
from types import (
    BuiltinFunctionType,
    ClassMethodDescriptorType,
    GetSetDescriptorType,
    MemberDescriptorType,
    MethodDescriptorType,
    ModuleType,
    WrapperDescriptorType,
)
from typing import Any

from .current_pixels_contract import MAX_PAYLOAD_BYTES, PROFILE, validate_resource_facts
from .errors import BridgeError, ErrorCode, invalid_argument

# CPython owns this warning cache. Establish its binding before source seals;
# ordinary deprecated RNA reads may populate it without adding module fields.
__warningregistry__ = {}

MAX_CANONICAL_BYTES = 16 * 1024 * 1024
MAX_VERTICES, MAX_EDGES, MAX_POLYGONS, MAX_LOOPS = 32_768, 65_536, 32_768, 131_072
MAX_UV_MAPS, MAX_SLOTS, MAX_NODES, MAX_LINKS, MAX_SOCKETS = 2, 16, 16, 16, 2048
LIFECYCLE_KEY = "_codex_bridge_current_pixels_lifecycle_v1"
BUILDS = {b"62c1db4208e8": (4, 5, 14), b"d13f752e3b9c": (5, 2, 2)}
SOCKETS = frozenset({"NodeSocketFloat", "NodeSocketFloatFactor", "NodeSocketFloatUnsigned",
                     "NodeSocketFloatDistance", "NodeSocketFloatAngle", "NodeSocketFloatWavelength", "NodeSocketColor",
                     "NodeSocketVector", "NodeSocketShader", "NodeSocketInt", "NodeSocketBool"})
NODES = frozenset({"ShaderNodeTexImage", "ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial"})
CENSUS_TYPES = ("ID", "BlendData", "Scene", "Collection", "Object", "MaterialSlot", "Mesh", "MeshVertex",
                "MeshEdge", "MeshPolygon", "MeshLoop", "UVLoopLayers", "MeshUVLoopLayer", "MeshUVLoop",
                "Attribute", "FloatVectorAttribute", "FloatVectorAttributeValue", "Int2Attribute", "Int2AttributeValue",
                "IntAttribute", "IntAttributeValue", "Float2Attribute", "Float2AttributeValue", "BoolAttribute",
                "BoolAttributeValue", "Material", "ShaderNodeTree", "Node", "NodeTree", "NodeSocket", "NodeLink",
                "ShaderNodeTexImage", "ShaderNodeBsdfPrincipled", "ShaderNodeOutputMaterial", "ImageUser", "Image",
                "PackedFile", "ColorManagedInputColorspaceSettings", "PropertyGroup", "CyclesMeshSettings",
                "CyclesObjectSettings", "CyclesMaterialSettings", "TexMapping", "ColorMapping", "ColorRamp",
                "ColorRampElement", "ColorRampElements", "NodePanelState", *sorted(SOCKETS))
# Complete ordered metadata pins from root's accepted official-build census.
# These do not authorize instance getters or prove mutation/recovery behavior.
_CATALOG_HASHES = ((b'62c1db4208e8',
  (('Attribute', '901b1c592d74d9bb508cd719d9eae8492abb57e70b213fed59eec2d4d7d2c487'),
   ('BlendData', 'af73b000866b63338f1f32ddc18e7590d0e4d9b0f2658cd6e62045569bc71db5'),
   ('BoolAttribute', 'aa9a162994b6e9648a4fe062800ab3037720b2cb879e76a0c9f5e228063928ad'),
   ('BoolAttributeValue', 'a742acee61e7f1e91c299fefe95eab4302fe29cbe4c1b9cd2492018c43ead6ab'),
   ('Collection', '30261d0de6ad9220f0101f9a221cd540b201b3b96aa3fa6541fb0415b38bf1e7'),
   ('ColorManagedInputColorspaceSettings',
    'c076cddea6f5c7542d45dbc149cb65c911244d9809391ab29aa30ac5ec8cf92b'),
   ('ColorMapping', '6a4295fb1b12d7aee8b81d7895dc62c9752f02bc01cd3ffcdd816f21d0396917'),
   ('ColorRamp', '2a6862edc83515dc76a44e86c587fb1558b5da65e522235e2f21f14b3d6a2509'),
   ('ColorRampElement', '3ef0ea1538ed3b3c7646bb0ba9d06ef8e2aed639460271f7f14cd41a5f56f200'),
   ('ColorRampElements', 'a85c533b6c331f49b9ad6993d7b6e0c6e94dd2413590c75c98b78ea7c11221c8'),
   ('Float2Attribute', '0229306167ceefedf044131a37279fe027ed447f650767910587d810c2b8ac99'),
   ('Float2AttributeValue', 'a7d1f15135cb7ea65652d629e4d172e36c791f046e87c6b82661619f9efcf1e1'),
   ('FloatVectorAttribute', 'bbce930ef58e855d5891f9dc665eb509ecdd36ac2e040033052889f5f73fd9d3'),
   ('FloatVectorAttributeValue', '126ef26861520349815f423906690c023ca837ea9f35163b48233280bb6ead08'),
   ('ID', 'df29b66c5f9ba0bd46204e2c72071f1d5b8a90b738de8e91cb5e049ef5c78fa3'),
   ('Image', 'd49da1b31ea0ff302ba428f6097b053c0a9d9cade63845ef78c91e1dddec4d18'),
   ('ImageUser', '630ffc9e986da9dceb8acf3f74636a21e926701c54bbd4d4aa8a0e30e66db8e9'),
   ('Int2Attribute', '937dd2a1309978a4aa2ef5143537deb5abc9385924d5bef7a745b636f9d63852'),
   ('Int2AttributeValue', '79f00e4a1ae859b19edcb4d9ad72d3dc44f1ab116c391aaf54669dac4ecf6f54'),
   ('IntAttribute', 'f95f88709ea3d03dfbb47b9719e3d060dececa3034fa5a4413c2c9917bcaf6db'),
   ('IntAttributeValue', '4ae59f6060ae5418d1b97b18bd50f5bc4c03a54b4738c91af44f6d334c65da3b'),
   ('Material', 'b02dcccb39beb95302d9260ef273ba11510f2db6fab2c51cafd9c1b12a54bd67'),
   ('MaterialSlot', '9749db07489998ce4f988d50583c7526fdfbbb3fffd4cfd96f68f9ff17638760'),
   ('Mesh', '3a73f48d9d6c2d16b69d5a869908b026cfb39e0590d34f73d4fba1b932fea3ad'),
   ('MeshEdge', 'd3b236f2953b3fa2d7a2955324e7c51cc5926a727becee7486c3b620846e4306'),
   ('MeshLoop', '6c9d5f87cf2170c5202837e52a8f1888323ccf8be8e4bfe16899fddf99e075b4'),
   ('MeshPolygon', 'ec0bd5244698a59a3201f8827b82d1a483eda060114cb366e18d97956de54867'),
   ('MeshUVLoop', '58929cc719928f0a30715c8102d0b514839c105dc0bc64b0af07b5faa1088802'),
   ('MeshUVLoopLayer', 'd836d2209413a1bf8a1e79565dc51a19b0698270f8e74fffa40c996743d883fb'),
   ('MeshVertex', 'c7e3ad8624f7034be3650af36fcde7602866335af25f28bf9639e0bf627e9962'),
   ('Node', 'd103cbe6b5de7cad2bf22017513b2ee057193bcedde53b9ab8fdc166acd7108f'),
   ('NodeLink', '0a1d2b248d22bf09379a40017ac0cf10c231133678ca62b1785488baec66b42e'),
   ('NodeSocket', 'b2136478abe93d0b5cc4dc3f9e9b029e398dc350e436a8b86f0e29072e5b38c0'),
   ('NodeSocketBool', 'a047af5cc18f75a981eca34e38744fa3465d0f530f11db76b449b258e32b6ea0'),
   ('NodeSocketColor', 'c1b0f8f14f5443778d3629eb58e9d8aa36a9a74dda76579384c4e8bebac7788b'),
   ('NodeSocketFloat', '40d9c2b1e0a8bc9dcf65bd9b9e750b812bb984f946ff89d10e8cf7fa3cde60e9'),
   ('NodeSocketFloatAngle', '1b8d56e685a27a422ce9d32d2dc25803a35afe5cb6ccd59e6c8432a0aeecc373'),
   ('NodeSocketFloatDistance', '831c70271a927e15c9ef78d4d4aef369e0dead743e161e71df7d34d1e7852948'),
   ('NodeSocketFloatFactor', 'b0e8793160662f17e4f9fdec46c691e88d93761651459d7885f4903fee9ee0c2'),
   ('NodeSocketFloatUnsigned', 'df1972e2eed84a1c0d068b2f955686aa0a18a3386f02941418eb83c44ccda88f'),
   ('NodeSocketFloatWavelength', '3634d2365d43e58dcc459a8df8ba039ac08212930c7c07f8cf7690ffbdd3aaa8'),
   ('NodeSocketInt', '014c9bbb0558a1e283e5c48739d36885e87f538c4d977dbf6350f7f7184036b9'),
   ('NodeSocketShader', '40fefcf3fe682c3b02dcc64d114f065864f0847d127f74d1facba3320a94b62e'),
   ('NodeSocketVector', '2f08bca144065de3c4af28a6c5ae9c8aba2dac541e1b118d6f36ebddb3c38534'),
   ('NodeTree', '9f695180b76e5f0a1e87d912c5c595a39caf2e7a6c239cd033e50f03d67d7b8a'),
   ('Object', 'eaa86567502eab8a6aa34ff4f7b8ac86dabace405d9b13a521f1da8f3ad75069'),
   ('PackedFile', 'c85a884ebc5d7d1b75f1388fae8958c1a8dac2239d56ac7dcf0ef49b2808a63e'),
   ('PropertyGroup', 'a841d622680e0fce4cb66e0aa1567009fa7c28d278c8b0c61aa8e80731bee86f'),
   ('Scene', 'cc7326038c9a76d195a9e2a3b89fd09e2b41efc6c705aecf9685325c8524ccdd'),
   ('ShaderNodeBsdfPrincipled', '1b6bcbe712dba7608bea21b67fa7dba03d91b159a2e65d1af6b66b72da1be56e'),
   ('ShaderNodeOutputMaterial', '355f7a5cb68e85f60c5bcf7ee06b4abd0ad1ee46e92b169d457a2b5976c0e3ad'),
   ('ShaderNodeTexImage', '36cb56528f91276eb6a952511e6e430210ac182554b7797f2756d6ce8a52e07e'),
   ('ShaderNodeTree', 'fb8f6c86b01609a0ec85a19ffa6c1cde64b99d6d88a1321513e1ea81e4e0a6bf'),
   ('TexMapping', 'af52cb9210505b50b82b60dd4e931afbe975f8722eb2fe030130238fd00c79c7'),
   ('UVLoopLayers', '7f0b479b4dd38bf314ae428ba853d2616c7a788feb51a199c8239df2d9fdf504'))),
 (b'd13f752e3b9c',
  (('Attribute', 'dac257d47f576f3ae0ecdfb03efc076cdd4350d1a3573c27fd9a1c5ea40db2a6'),
   ('BlendData', '2c414e2b2ac7fa8789bcf2de708bdde2bc3f26d3d753a11422d0a15bd6647b61'),
   ('BoolAttribute', '27e7e569c1a8de7d4898496299f807155748837bff7ef5894f3cef47c7cb954c'),
   ('BoolAttributeValue', 'a742acee61e7f1e91c299fefe95eab4302fe29cbe4c1b9cd2492018c43ead6ab'),
   ('Collection', 'e3c2bac6c17e2adc5cadca1327c6166a2f389378aadd4bbf353d3c0f3b44b6d6'),
   ('ColorManagedInputColorspaceSettings',
    'c076cddea6f5c7542d45dbc149cb65c911244d9809391ab29aa30ac5ec8cf92b'),
   ('ColorMapping', '6a4295fb1b12d7aee8b81d7895dc62c9752f02bc01cd3ffcdd816f21d0396917'),
   ('ColorRamp', '2a6862edc83515dc76a44e86c587fb1558b5da65e522235e2f21f14b3d6a2509'),
   ('ColorRampElement', '3ef0ea1538ed3b3c7646bb0ba9d06ef8e2aed639460271f7f14cd41a5f56f200'),
   ('ColorRampElements', 'a85c533b6c331f49b9ad6993d7b6e0c6e94dd2413590c75c98b78ea7c11221c8'),
   ('Float2Attribute', '5446595ccd51fb4a39a35ae7b214c9758d02feb3cfbe294795375c693af185f6'),
   ('Float2AttributeValue', 'a7d1f15135cb7ea65652d629e4d172e36c791f046e87c6b82661619f9efcf1e1'),
   ('FloatVectorAttribute', 'f14ee1b48027226b263aacbd50a50a7ddca6ad696cd8492d81475dcde657f540'),
   ('FloatVectorAttributeValue', '126ef26861520349815f423906690c023ca837ea9f35163b48233280bb6ead08'),
   ('ID', '40fd30c9c3a71dfb9d2299bf3ae7f8e8ac58a2dfc5e8effe5313de3e3b8aa556'),
   ('Image', '0ea94df4adb3b1c7e2944d42f5bdd970eb7352b91bb462d5ab5ea9cfd20867dc'),
   ('ImageUser', '630ffc9e986da9dceb8acf3f74636a21e926701c54bbd4d4aa8a0e30e66db8e9'),
   ('Int2Attribute', '4a691c23cbbba7fe8ad93b71f2653a7c9cfa1110642d25e5a2a50989805e0a6e'),
   ('Int2AttributeValue', '79f00e4a1ae859b19edcb4d9ad72d3dc44f1ab116c391aaf54669dac4ecf6f54'),
   ('IntAttribute', '791491ea49f3d0bd6b2662a93e3b7a5da124da59a09f69981aa232a06702977e'),
   ('IntAttributeValue', '4ae59f6060ae5418d1b97b18bd50f5bc4c03a54b4738c91af44f6d334c65da3b'),
   ('Material', '521e99d088d743d0b856e0a6c1d309379bd45bd82abe6829b9ffe8a12796e8d6'),
   ('MaterialSlot', '9749db07489998ce4f988d50583c7526fdfbbb3fffd4cfd96f68f9ff17638760'),
   ('Mesh', 'e0dfb4ba116e0cae70249e5bff752ef5f396fb9ca670283563ec2a531a350329'),
   ('MeshEdge', '326d5bdeaabcaa9915babdbe446ed0391d92129cd3ecc67fdba5b24fb5c12b95'),
   ('MeshLoop', '6c9d5f87cf2170c5202837e52a8f1888323ccf8be8e4bfe16899fddf99e075b4'),
   ('MeshPolygon', 'd60183a0636675e8a242746858f640b495f62b6f848869be049905352a2ee2b5'),
   ('MeshUVLoop', '14ae009b6cf7fc8387538e69710ff9c150fdb861d4f10836802996e1ca96cc57'),
   ('MeshUVLoopLayer', '606da4f5bd14e1130b9d368b0b98e049faa986f0f7adda2270553defe3977620'),
   ('MeshVertex', 'c7e3ad8624f7034be3650af36fcde7602866335af25f28bf9639e0bf627e9962'),
   ('Node', 'fcd914fd3b3a4567276b2e6c95c3858556dffd4b6efdae141bb1cd224fb65fe7'),
   ('NodeLink', '0a1d2b248d22bf09379a40017ac0cf10c231133678ca62b1785488baec66b42e'),
   ('NodePanelState', '6f4c6309e86c889ab60b4091bb715c2d960d41ff249f7b06c65f13eb1f4ec4f4'),
   ('NodeSocket', '7f190f13b3a9bd4505407332754120e7325c7c8b87d98cb87f1fca96a1fe96ae'),
   ('NodeSocketBool', '17ef29307828de524fc4e6f81b329f42c3e0a63db540e1f814b14d8c482b341f'),
   ('NodeSocketColor', '71306d5ca90ea30b009f142f11561fdf048715da8a1ec2258d4eaf7b852e895c'),
   ('NodeSocketFloat', '00954e71dc73ee41174ca35e8a1d778b7201afd8bc0325f283022d63de97dc8f'),
   ('NodeSocketFloatAngle', '232fa779675154d4d6e9ea19c7633bcade262b6eed8f78d690cf1bf23709a42d'),
   ('NodeSocketFloatDistance', 'a42372bbdd7db9918731c6ab4a0d09764aca3e81102e157c972c9bc04959fa95'),
   ('NodeSocketFloatFactor', '68fb4ddeb0cf5d98697d38f93351006ff6841a5dfb5e2f7d7a7566fbeae44c8f'),
   ('NodeSocketFloatUnsigned', 'eaf800d3f2160c802b802737c272d34991f39f29bc43cb892ef2b8577ecbe888'),
   ('NodeSocketFloatWavelength', 'dbbaacb165fbb6870134a1ab12c28a7a04dff206f8e5bf4c8c6579bb70712caa'),
   ('NodeSocketInt', 'c72399fe53185684bbb7c576a8bfa780577c458e0424139bf105b022c996d530'),
   ('NodeSocketShader', '32048a347a0ecad25282d9479a450681a9a737763727023af40db203b736107f'),
   ('NodeSocketVector', 'c8c11c333533432aeb91037a3c906cd0170151a8e9fd1c24be98e3541e5847fc'),
   ('NodeTree', '5b8e88e02ddc392372d8b607866c556786fe4d41d61116c18564f91ac991000f'),
   ('Object', '24f8d953cb82749b4db74e8bc7aacd51e88e55f0f4f5162d9c6d15281e2772d5'),
   ('PackedFile', 'c85a884ebc5d7d1b75f1388fae8958c1a8dac2239d56ac7dcf0ef49b2808a63e'),
   ('PropertyGroup', '1f26afeb38bcc8d75712caa484fe4193c7992571c2e22aef6082460d50d9168f'),
   ('Scene', '70bdc37b0e3118e10168220f6f6adfd032c8878e769cfc8d2ec3da0312686ef9'),
   ('ShaderNodeBsdfPrincipled', 'e5e49680a3118cc98c9afeff1f0dac4d5dfc7c5fd0494a299ebaa0b2091d52be'),
   ('ShaderNodeOutputMaterial', 'f57354492f84185ff19601f53b6077c8007d82ba351c06c82a3d505d2c4310e3'),
   ('ShaderNodeTexImage', '97eaeaf5ca879a29c9e45f75403a00371980d9e7425a54817244103ef08782d2'),
   ('ShaderNodeTree', '982e07103a45bb948f5e40c0f99217b9f251cab9e0fa3e1d0ddffa6230953f20'),
   ('TexMapping', 'af52cb9210505b50b82b60dd4e931afbe975f8722eb2fe030130238fd00c79c7'),
   ('UVLoopLayers', '7496918ac6ac0f2f3bc9028c7cd306f67ef94fed7de1ef8f74a55ea91eb8dda2'))))
_STATIC_CATALOG_HASHES = ((b'62c1db4208e8',
  (('Attribute', '2cfcefa6256f8e79cc9cd34b70073db37505666a08e0bb371f72f4192cce95fa'),
   ('BlendData', 'f36d790f4366f89cbaf0d3b3dcf384fb13ab6ff98724705aab6147323a925ac3'),
   ('BoolAttribute', '9cdad8d0c0e61974521425f92096a9f62460f1cfd27b5243f4a5c0ef39d0b595'),
   ('BoolAttributeValue', '481755b0ff5032b779beb77003061e9b8c4545900252a91eba8b050aed9832e4'),
   ('Collection', 'f41590c135c164f31091cae1c5f144ff8d64ba52bf1ec41c82f7dc2cf2a9995b'),
   ('ColorManagedInputColorspaceSettings',
    '26575670c79ec5a4bd8a47e5b6f04791e9fab3eb588253e0b8cfb37b0ff108b6'),
   ('ColorMapping', '5a4b0e9157a9f26ca8c86a64b4e7b133d1460cae3803d9eadefe821862c5f33d'),
   ('ColorRamp', 'eba726c9b3198ceffd6726269f0e38ac5650a7c29b72b65da302d50b160a4500'),
   ('ColorRampElement', '0ea768cb97fe52d11640c87d01599b9eba784e7dc1687c5537da17b650d74b0f'),
   ('ColorRampElements', 'cc6b96f2f24a44262a2956141e6adfa1dea059c73eaf7b2f855f1d82a486b473'),
   ('Float2Attribute', '8c6a0e1eb34cf29c5466979f0e61dbbde9148ec5ae642dd790f94369f41cbf90'),
   ('Float2AttributeValue', 'b390c40391e482d9fc6bc316ce27b7548076d4e1f4d75ecda3cfbd9d75ec68e3'),
   ('FloatVectorAttribute', '6c30975321f194ce349d5a76e0a4ebb74e23c4fb36b5a317dcbfd8cac9538343'),
   ('FloatVectorAttributeValue', '491a8208c9a1c5b31b2480f866954dcac986d6a7bd3160144f626d03cfb134f1'),
   ('ID', 'bb0a61ed438382513204d6fe793186852ac073e508d5469dd3153c7f863b20b4'),
   ('Image', 'b2223f7f5498a5ec3db9088c2dd5c59119a7afa3b765d4515208d5ad25f62d06'),
   ('ImageUser', '1df5bc20d967d509fe562d81e46fa02e418ff02c0eee72425d7de2daf968e82d'),
   ('Int2Attribute', '181b3e4369038ed0eb84807f0d44f37efbc954c4b87d44baf7c1f0638c5812e9'),
   ('Int2AttributeValue', '2d862591efde9283aed45a53f5eeb8d8cc0b10cdf36004b268a57ab707dc64e8'),
   ('IntAttribute', '6757ed2a1d9f796a6db575f009b4df0c46713a58716c37433cd2a807a00e3748'),
   ('IntAttributeValue', '8da39df9cdc1441eac4357eebcd4c98ef8b5a6a12514ce8ba0d8136840bf2d26'),
   ('Material', 'b78a897c8c50499df6d5ad9287e8717e2c5c19337ff5b05b79137aab65dd2177'),
   ('MaterialSlot', 'e9e3d0b6b46973f6b2c73beb65cea05e1047fb478c3f496a3ca5e4e94861b1d4'),
   ('Mesh', 'ae7519517056f77859aca9e1927eb8a49d2dc41e7adb2af0c028025fcfebe73f'),
   ('MeshEdge', '58e230ba01baa652cb58571e076eaefe34b2aa5a2092ea089548320f81f680ac'),
   ('MeshLoop', '729fb5b540ef03261a999e713deb31c9d776d37adc7ea5718191365ff432e115'),
   ('MeshPolygon', '683fd1317a7b3e75f3308243fbc79a28f7db67bd429ff9e77add71357c8cd419'),
   ('MeshUVLoop', '680953d482e26e551f43086309784df4cbcbab9c111be232a8caa4f4bc5386f6'),
   ('MeshUVLoopLayer', '1ecdce7a3c8b3b2316bdca78bb8250331f7683edc8ac81c2d9afe23196b93098'),
   ('MeshVertex', '10515be42f3ca0800b359a7bf094ac84c47c2649447a1c76137aba03d77d659d'),
   ('Node', '1cc1e5582049d0266f18da5bc1b1fe6e76e10dd137bbc24d9e35574a7b06a164'),
   ('NodeLink', 'cbda178af90861be6412da2b299986a7648f1de12b432ebfb382b0eca081ec11'),
   ('NodeSocket', 'ba480b03f044dffbe88193251aa82b44e3226c3b910f1189969378fa2ac0d64b'),
   ('NodeSocketBool', '2a0818f34a79b5ee1585e0c3c7e196c31304402fd7b53b7a2e75e306899e5b78'),
   ('NodeSocketColor', '20046a125f4018895f74f6bc08ed172fb4f000919d77b50ccfb4ecc8503bbca2'),
   ('NodeSocketFloat', '10aee8543713542bd13603a95865fb39ef1d2a1f131f7afa868c0b07d4c83883'),
   ('NodeSocketFloatAngle', '57f4f31e943a8941c9056924b01764490a852ed89f9584cd9bb491944dcff67c'),
   ('NodeSocketFloatDistance', '34327205709749dfdd97d8aea25327d2788b1b3eeef466716217830a51ef4c09'),
   ('NodeSocketFloatFactor', '533a773fedf92b1c19235f72d709a6691f85ca2752499f1aecc165cba1155709'),
   ('NodeSocketFloatUnsigned', '79dd055cdc61887698567fc1ba12b4b7854a0cfa82a2cafc355c1205a16b1a04'),
   ('NodeSocketFloatWavelength', 'a3a0e86056ccfcf07772b641ef27c2ecab9ed8c15e314a7d7a65dae1211ca432'),
   ('NodeSocketInt', 'b5645916a53d56ffc1d3435575a32b347298d9e33b8fade5dfdf53317bd6245f'),
   ('NodeSocketShader', 'b57b5b607c2b259bea8816b158161e490cd9bd5a8b0263f1c0f698f5672e62c1'),
   ('NodeSocketVector', '739332b8aae082a387809eee337c8d3ada4f3a040a820a55bff06dc45f59ffd5'),
   ('NodeTree', 'b5b5ca61e45617f908daa55c7c086765c4d58bf97c64d7ee0958cf2795217105'),
   ('Object', '6f73b7314afd96d777e7d7e4313934a9c262140bdb1f20be99afe40e0220ec9c'),
   ('PackedFile', 'f114bb52ee24469c81df7fcef6b56add302a26cd5de849ecac3fdd22854e9ba6'),
   ('PropertyGroup', '5d83439202aebc9213d12b35d9dfa62cf48e4a52ec5caeaf170552dae2e7c507'),
   ('Scene', 'd962fd2772f1f65fd879ac3b571a60f24a07388344ba749254c5bcc7408bd108'),
   ('ShaderNodeBsdfPrincipled', 'b78d46d7373f5cbd66a90d274303e94700e4af027fa721bd3645e9e0e5716a54'),
   ('ShaderNodeOutputMaterial', 'e8fe89a68fca8ba64c93518083709dc2b67e65911fe3b08d41899e96b9850f39'),
   ('ShaderNodeTexImage', '9624ca7f017a67124005761b0d292b828733fb03371d061ff2f8998f87aecbca'),
   ('ShaderNodeTree', '74eedcfc0c041583415f82a872682805bdbc681177bd8454821f26aa6568e4d8'),
   ('TexMapping', '1e13afdeb8a6a9ca3ad7994c439c2159440dd732dd5b1a0e8183949227b5e5a0'),
   ('UVLoopLayers', '4a2be695e027ea236e16e13aa937ddf3943c01541dd6ee1decd0cd8fedae8dfa'))),
 (b'd13f752e3b9c',
  (('Attribute', '5468d8ee1b7c4c8c63bdfbd4ee28d54e7fa298485621a9e17f9aa1bb5a094724'),
   ('BlendData', '7fa6f5dfcc6d3f0d1c50584dc5a42aaf7076ac002d4e9e930936e592fa06bff3'),
   ('BoolAttribute', '05fd757ae09ca2e901fb7d90bffeb19d1c90b222d78e612479e34afac1f4e979'),
   ('BoolAttributeValue', '481755b0ff5032b779beb77003061e9b8c4545900252a91eba8b050aed9832e4'),
   ('Collection', 'f34465d8542064d40cc906e49fb462f8e7c7de99862fd36ccb79d33c738a1084'),
   ('ColorManagedInputColorspaceSettings',
    '26575670c79ec5a4bd8a47e5b6f04791e9fab3eb588253e0b8cfb37b0ff108b6'),
   ('ColorMapping', '5a4b0e9157a9f26ca8c86a64b4e7b133d1460cae3803d9eadefe821862c5f33d'),
   ('ColorRamp', 'eba726c9b3198ceffd6726269f0e38ac5650a7c29b72b65da302d50b160a4500'),
   ('ColorRampElement', '0ea768cb97fe52d11640c87d01599b9eba784e7dc1687c5537da17b650d74b0f'),
   ('ColorRampElements', 'cc6b96f2f24a44262a2956141e6adfa1dea059c73eaf7b2f855f1d82a486b473'),
   ('Float2Attribute', 'fed3f50db82c61abc812973339328c5e8adb0d463258e52e518cab369d300080'),
   ('Float2AttributeValue', 'b390c40391e482d9fc6bc316ce27b7548076d4e1f4d75ecda3cfbd9d75ec68e3'),
   ('FloatVectorAttribute', '45fe739ffcf73bdc04996f144e6764967d0966d3c3626f4d5a7257b71329ee2c'),
   ('FloatVectorAttributeValue', '491a8208c9a1c5b31b2480f866954dcac986d6a7bd3160144f626d03cfb134f1'),
   ('ID', '835cb1ccb0321d6a7bdf71b59040c55d4944e8dd4d832bb867ba7685ef59a6dd'),
   ('Image', '7a89d5d647f3b9ae52ee4ef4e69f516a9db5ed01f85002c608227f0806b767df'),
   ('ImageUser', '1df5bc20d967d509fe562d81e46fa02e418ff02c0eee72425d7de2daf968e82d'),
   ('Int2Attribute', '0e218ee26bca5e02d85a0525611cd55e6804ad801f3e4e01852a871cc0f99e62'),
   ('Int2AttributeValue', '2d862591efde9283aed45a53f5eeb8d8cc0b10cdf36004b268a57ab707dc64e8'),
   ('IntAttribute', '9ec3a9e2296bb086e087d547971b4499d208c26103f35f5551063379e0d91875'),
   ('IntAttributeValue', '8da39df9cdc1441eac4357eebcd4c98ef8b5a6a12514ce8ba0d8136840bf2d26'),
   ('Material', '8df75cf0932b4a1219e544dfe2165c564d6adfbc841ff347c0eb70abc0e87201'),
   ('MaterialSlot', 'e9e3d0b6b46973f6b2c73beb65cea05e1047fb478c3f496a3ca5e4e94861b1d4'),
   ('Mesh', '94d5f9b94d363bb0efdf48e59cea17a20ddfceeb8cc06201196117ae005d8ce3'),
   ('MeshEdge', '13147bbd680afecbb1549b18dcb2e39959e2f1053f47605735305f80376c74bc'),
   ('MeshLoop', '729fb5b540ef03261a999e713deb31c9d776d37adc7ea5718191365ff432e115'),
   ('MeshPolygon', '1ac081e49a11a82e925ab70dffdcdaf2f9120d4ae9b45b9f15c9a3bc5574b3c1'),
   ('MeshUVLoop', '32545d40c4e60142d87ff9c7f9ded7da8ac2ab3f01de97857b9bf4490dc0923d'),
   ('MeshUVLoopLayer', '69caf652ee550df0c810cedbb57b7e634902df21af52af8158c87d4cd81da731'),
   ('MeshVertex', '10515be42f3ca0800b359a7bf094ac84c47c2649447a1c76137aba03d77d659d'),
   ('Node', '09bca1442365ee281dcf1b80326f75b63672ab285f5b8ff72a66679382f5626d'),
   ('NodeLink', 'cbda178af90861be6412da2b299986a7648f1de12b432ebfb382b0eca081ec11'),
   ('NodePanelState', '55e188e79c7e06a1622960cc0aa7711be1eb062277e5d85a818157b09187f79f'),
   ('NodeSocket', '23e634fb3d827434c268cf0471c5f9e15caa2b040738e0faadbb53d517f1708d'),
   ('NodeSocketBool', '7d9b25b4023b7b8be1c142a6d69229d0069340047a8dd190c81e6c72457ceb1f'),
   ('NodeSocketColor', 'bb468c5da92b664a4fb6f0a42d8cd10bcf9c07174fa3e31be421b76652cf0281'),
   ('NodeSocketFloat', 'e0f64bd91fb3f4cdc715ebef52ef46a5d01e77ae91740c6a2d850211520592e0'),
   ('NodeSocketFloatAngle', 'a57449ec89ef44278ffb16996f03d1f892e8a45176a7a3d6dd02c4618984040d'),
   ('NodeSocketFloatDistance', 'c32403e83e90a9c8e53caf55c61f73df1ae7cba64b96719ccac3c28595d05577'),
   ('NodeSocketFloatFactor', 'b06ded1437773456bd4d9c55c1ea0cd6957cc265c4542da2d0e23b7dc005481a'),
   ('NodeSocketFloatUnsigned', '88467bf2b3d2a970ef347ba228ab8a73a55b1038af209e6c8c4a219dd200d7e9'),
   ('NodeSocketFloatWavelength', '7f011f6ad5619a12d0062049c2f77648bcfac16b6d3094a9f949be8254d019c8'),
   ('NodeSocketInt', '90a7f2dd790abd115132dd08704d3192aac5da264d7c4fc6d804121e314a042b'),
   ('NodeSocketShader', 'dbc789e73eb09ad371c3c1ddb5a0ecd74cbfbd3e757b856b4d8ca43a69eb31c9'),
   ('NodeSocketVector', 'f58bd63f28548bf74b626507410aef75eedff4ae4e3d0cf349e407d027af7f23'),
   ('NodeTree', '9b71787763e799671d7e3074888032a17aeddd129156b468ca9555c1ecc1b94a'),
   ('Object', 'b70d754d2efe26fdbaf3a660048c2ff5b70f34a920eb23ab0856d8bdae824d46'),
   ('PackedFile', 'f114bb52ee24469c81df7fcef6b56add302a26cd5de849ecac3fdd22854e9ba6'),
   ('PropertyGroup', '1647e0208d26cb9149454f12f56aa994406b871bbc2ea3d553e689f91d474136'),
   ('Scene', 'fa828d4873640a5da0115bb09506615443f3106a48f3ac958af12c5eba6aa8d4'),
   ('ShaderNodeBsdfPrincipled', '7b43238129c5bb6b98cfbc400ae04066f4df28b9d27ab3b96fb8647b87d6e16e'),
   ('ShaderNodeOutputMaterial', 'faefefaa94b36d4346973c8d63a126816d94cd47772d3fd6fa9b7af0bd700c34'),
   ('ShaderNodeTexImage', '034c1f0bfb2c37d1fe6d2fbe7a4d39b73a463d24ad86b7976c6c1130c3324d52'),
   ('ShaderNodeTree', '713a1eb48ae66a1d40a409719ce26b13213e6b4b61143ef92e79c540719e3f62'),
   ('TexMapping', '1e13afdeb8a6a9ca3ad7994c439c2159440dd732dd5b1a0e8183949227b5e5a0'),
   ('UVLoopLayers', '43a841fa1fed91f4a9d1824e697142b6056132e5efc76836e0583516c86d6952'))))
_FIXED_TARGETS = ((b'62c1db4208e8',
  (('Attribute', (('rna_type', 'Struct'),)),
   ('BlendData',
    (('actions', 'Action'),
     ('armatures', 'Armature'),
     ('brushes', 'Brush'),
     ('cache_files', 'CacheFile'),
     ('cameras', 'Camera'),
     ('collections', 'Collection'),
     ('curves', 'Curve'),
     ('fonts', 'VectorFont'),
     ('grease_pencils', 'GreasePencil'),
     ('grease_pencils_v3', 'GreasePencilv3'),
     ('hair_curves', 'Curves'),
     ('images', 'Image'),
     ('lattices', 'Lattice'),
     ('libraries', 'Library'),
     ('lightprobes', 'LightProbe'),
     ('lights', 'Light'),
     ('linestyles', 'FreestyleLineStyle'),
     ('masks', 'Mask'),
     ('materials', 'Material'),
     ('meshes', 'Mesh'),
     ('metaballs', 'MetaBall'),
     ('movieclips', 'MovieClip'),
     ('node_groups', 'NodeTree'),
     ('objects', 'Object'),
     ('paint_curves', 'PaintCurve'),
     ('palettes', 'Palette'),
     ('particles', 'ParticleSettings'),
     ('pointclouds', 'PointCloud'),
     ('rna_type', 'Struct'),
     ('scenes', 'Scene'),
     ('screens', 'Screen'),
     ('shape_keys', 'Key'),
     ('sounds', 'Sound'),
     ('speakers', 'Speaker'),
     ('texts', 'Text'),
     ('textures', 'Texture'),
     ('volumes', 'Volume'),
     ('window_managers', 'WindowManager'),
     ('workspaces', 'WorkSpace'),
     ('worlds', 'World'))),
   ('BoolAttribute', (('data', 'BoolAttributeValue'), ('rna_type', 'Struct'))),
   ('BoolAttributeValue', (('rna_type', 'Struct'),)),
   ('Collection',
    (('all_objects', 'Object'),
     ('asset_data', 'AssetMetaData'),
     ('children', 'Collection'),
     ('collection_children', 'CollectionChild'),
     ('collection_objects', 'CollectionObject'),
     ('exporters', 'CollectionExport'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('objects', 'Object'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('ColorManagedInputColorspaceSettings', (('rna_type', 'Struct'),)),
   ('ColorMapping', (('color_ramp', 'ColorRamp'), ('rna_type', 'Struct'))),
   ('ColorRamp', (('elements', 'ColorRampElement'), ('rna_type', 'Struct'))),
   ('ColorRampElement', (('rna_type', 'Struct'),)),
   ('ColorRampElements', (('rna_type', 'Struct'),)),
   ('Float2Attribute', (('data', 'Float2AttributeValue'), ('rna_type', 'Struct'))),
   ('Float2AttributeValue', (('rna_type', 'Struct'),)),
   ('FloatVectorAttribute', (('data', 'FloatVectorAttributeValue'), ('rna_type', 'Struct'))),
   ('FloatVectorAttributeValue', (('rna_type', 'Struct'),)),
   ('ID',
    (('asset_data', 'AssetMetaData'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('Image',
    (('asset_data', 'AssetMetaData'),
     ('colorspace_settings', 'ColorManagedInputColorspaceSettings'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('packed_file', 'PackedFile'),
     ('packed_files', 'ImagePackedFile'),
     ('preview', 'ImagePreview'),
     ('render_slots', 'RenderSlot'),
     ('rna_type', 'Struct'),
     ('stereo_3d_format', 'Stereo3dFormat'),
     ('tiles', 'UDIMTile'))),
   ('ImageUser', (('rna_type', 'Struct'),)),
   ('Int2Attribute', (('data', 'Int2AttributeValue'), ('rna_type', 'Struct'))),
   ('Int2AttributeValue', (('rna_type', 'Struct'),)),
   ('IntAttribute', (('data', 'IntAttributeValue'), ('rna_type', 'Struct'))),
   ('IntAttributeValue', (('rna_type', 'Struct'),)),
   ('Material',
    (('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('cycles', 'CyclesMaterialSettings'),
     ('grease_pencil', 'MaterialGPencilStyle'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('lineart', 'MaterialLineArt'),
     ('node_tree', 'NodeTree'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'),
     ('texture_paint_images', 'Image'),
     ('texture_paint_slots', 'TexPaintSlot'))),
   ('MaterialSlot', (('material', 'Material'), ('rna_type', 'Struct'))),
   ('Mesh',
    (('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('attributes', 'Attribute'),
     ('color_attributes', 'Attribute'),
     ('corner_normals', 'MeshNormalValue'),
     ('cycles', 'CyclesMeshSettings'),
     ('edges', 'MeshEdge'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('loop_triangle_polygons', 'ReadOnlyInteger'),
     ('loop_triangles', 'MeshLoopTriangle'),
     ('loops', 'MeshLoop'),
     ('materials', 'Material'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('polygon_normals', 'MeshNormalValue'),
     ('polygons', 'MeshPolygon'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'),
     ('shape_keys', 'Key'),
     ('skin_vertices', 'MeshSkinVertexLayer'),
     ('texco_mesh', 'Mesh'),
     ('texture_mesh', 'Mesh'),
     ('uv_layer_clone', 'MeshUVLoopLayer'),
     ('uv_layer_stencil', 'MeshUVLoopLayer'),
     ('uv_layers', 'MeshUVLoopLayer'),
     ('vertex_colors', 'MeshLoopColorLayer'),
     ('vertex_normals', 'MeshNormalValue'),
     ('vertices', 'MeshVertex'))),
   ('MeshEdge', (('rna_type', 'Struct'),)),
   ('MeshLoop', (('rna_type', 'Struct'),)),
   ('MeshPolygon', (('rna_type', 'Struct'),)),
   ('MeshUVLoop', (('rna_type', 'Struct'),)),
   ('MeshUVLoopLayer',
    (('data', 'MeshUVLoop'),
     ('edge_selection', 'BoolAttributeValue'),
     ('pin', 'BoolAttributeValue'),
     ('rna_type', 'Struct'),
     ('uv', 'Float2AttributeValue'),
     ('vertex_selection', 'BoolAttributeValue'))),
   ('MeshVertex', (('groups', 'VertexGroupElement'), ('rna_type', 'Struct'))),
   ('Node',
    (('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'))),
   ('NodeLink',
    (('from_node', 'Node'),
     ('from_socket', 'NodeSocket'),
     ('rna_type', 'Struct'),
     ('to_node', 'Node'),
     ('to_socket', 'NodeSocket'))),
   ('NodeSocket', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketBool', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketColor', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloat', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatAngle', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatDistance', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatFactor', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatUnsigned', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatWavelength', (('rna_type', 'Struct'), ('node', 'Node'))),
   ('NodeSocketInt', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketShader', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketVector', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeTree',
    (('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('grease_pencil', 'GreasePencil'),
     ('interface', 'NodeTreeInterface'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('links', 'NodeLink'),
     ('nodes', 'Node'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('Object',
    (('active_material', 'Material'),
     ('active_shape_key', 'ShapeKey'),
     ('animation_data', 'AnimData'),
     ('animation_visualization', 'AnimViz'),
     ('asset_data', 'AssetMetaData'),
     ('collision', 'CollisionSettings'),
     ('constraints', 'Constraint'),
     ('cycles', 'CyclesObjectSettings'),
     ('data', 'ID'),
     ('display', 'ObjectDisplay'),
     ('field', 'FieldSettings'),
     ('image_user', 'ImageUser'),
     ('instance_collection', 'Collection'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('light_linking', 'ObjectLightLinking'),
     ('lineart', 'ObjectLineArt'),
     ('material_slots', 'MaterialSlot'),
     ('modifiers', 'Modifier'),
     ('motion_path', 'MotionPath'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('parent', 'Object'),
     ('particle_systems', 'ParticleSystem'),
     ('pose', 'Pose'),
     ('preview', 'ImagePreview'),
     ('rigid_body', 'RigidBodyObject'),
     ('rigid_body_constraint', 'RigidBodyConstraint'),
     ('rna_type', 'Struct'),
     ('selection_sets', 'SelectionSet'),
     ('shader_effects', 'ShaderFx'),
     ('soft_body', 'SoftBodySettings'),
     ('vertex_groups', 'VertexGroup'))),
   ('PackedFile', (('rna_type', 'Struct'),)),
   ('PropertyGroup', (('rna_type', 'Struct'),)),
   ('Scene',
    (('active_clip', 'MovieClip'),
     ('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('background_set', 'Scene'),
     ('camera', 'Object'),
     ('collection', 'Collection'),
     ('cursor', 'View3DCursor'),
     ('cycles', 'CyclesRenderSettings'),
     ('cycles_curves', 'CyclesCurveRenderSettings'),
     ('display', 'SceneDisplay'),
     ('display_settings', 'ColorManagedDisplaySettings'),
     ('eevee', 'SceneEEVEE'),
     ('grease_pencil', 'GreasePencil'),
     ('grease_pencil_settings', 'SceneGpencil'),
     ('hydra', 'SceneHydra'),
     ('keying_sets', 'KeyingSet'),
     ('keying_sets_all', 'KeyingSet'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('node_tree', 'NodeTree'),
     ('objects', 'Object'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('render', 'RenderSettings'),
     ('rigidbody_world', 'RigidBodyWorld'),
     ('rna_type', 'Struct'),
     ('safe_areas', 'DisplaySafeAreas'),
     ('sequence_editor', 'SequenceEditor'),
     ('sequencer_colorspace_settings', 'ColorManagedSequencerColorspaceSettings'),
     ('timeline_markers', 'TimelineMarker'),
     ('tool_settings', 'ToolSettings'),
     ('transform_orientation_slots', 'TransformOrientationSlot'),
     ('unit_settings', 'UnitSettings'),
     ('view_layers', 'ViewLayer'),
     ('view_settings', 'ColorManagedViewSettings'),
     ('world', 'World'))),
   ('ShaderNodeBsdfPrincipled',
    (('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'))),
   ('ShaderNodeOutputMaterial',
    (('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'))),
   ('ShaderNodeTexImage',
    (('color_mapping', 'ColorMapping'),
     ('image', 'Image'),
     ('image_user', 'ImageUser'),
     ('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'),
     ('texture_mapping', 'TexMapping'))),
   ('ShaderNodeTree',
    (('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('grease_pencil', 'GreasePencil'),
     ('interface', 'NodeTreeInterface'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('links', 'NodeLink'),
     ('nodes', 'Node'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('TexMapping', (('rna_type', 'Struct'),)),
   ('UVLoopLayers', (('active', 'MeshUVLoopLayer'), ('rna_type', 'Struct'))))),
 (b'd13f752e3b9c',
  (('Attribute', (('rna_type', 'Struct'),)),
   ('BlendData',
    (('actions', 'Action'),
     ('all_ids', 'ID'),
     ('annotations', 'Annotation'),
     ('armatures', 'Armature'),
     ('brushes', 'Brush'),
     ('cache_files', 'CacheFile'),
     ('cameras', 'Camera'),
     ('collections', 'Collection'),
     ('colorspace', 'BlendFileColorspace'),
     ('curves', 'Curve'),
     ('fonts', 'VectorFont'),
     ('grease_pencils', 'GreasePencil'),
     ('hair_curves', 'Curves'),
     ('images', 'Image'),
     ('lattices', 'Lattice'),
     ('libraries', 'Library'),
     ('lightprobes', 'LightProbe'),
     ('lights', 'Light'),
     ('linestyles', 'FreestyleLineStyle'),
     ('masks', 'Mask'),
     ('materials', 'Material'),
     ('meshes', 'Mesh'),
     ('metaballs', 'MetaBall'),
     ('movieclips', 'MovieClip'),
     ('node_groups', 'NodeTree'),
     ('objects', 'Object'),
     ('paint_curves', 'PaintCurve'),
     ('palettes', 'Palette'),
     ('particles', 'ParticleSettings'),
     ('pointclouds', 'PointCloud'),
     ('rna_type', 'Struct'),
     ('scenes', 'Scene'),
     ('screens', 'Screen'),
     ('shape_keys', 'Key'),
     ('sounds', 'Sound'),
     ('speakers', 'Speaker'),
     ('texts', 'Text'),
     ('textures', 'Texture'),
     ('volumes', 'Volume'),
     ('window_managers', 'WindowManager'),
     ('workspaces', 'WorkSpace'),
     ('worlds', 'World'))),
   ('BoolAttribute', (('data', 'BoolAttributeValue'), ('rna_type', 'Struct'))),
   ('BoolAttributeValue', (('rna_type', 'Struct'),)),
   ('Collection',
    (('all_objects', 'Object'),
     ('asset_data', 'AssetMetaData'),
     ('children', 'Collection'),
     ('collection_children', 'CollectionChild'),
     ('collection_objects', 'CollectionObject'),
     ('exporters', 'CollectionExport'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('objects', 'Object'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('ColorManagedInputColorspaceSettings', (('rna_type', 'Struct'),)),
   ('ColorMapping', (('color_ramp', 'ColorRamp'), ('rna_type', 'Struct'))),
   ('ColorRamp', (('elements', 'ColorRampElement'), ('rna_type', 'Struct'))),
   ('ColorRampElement', (('rna_type', 'Struct'),)),
   ('ColorRampElements', (('rna_type', 'Struct'),)),
   ('Float2Attribute', (('data', 'Float2AttributeValue'), ('rna_type', 'Struct'))),
   ('Float2AttributeValue', (('rna_type', 'Struct'),)),
   ('FloatVectorAttribute', (('data', 'FloatVectorAttributeValue'), ('rna_type', 'Struct'))),
   ('FloatVectorAttributeValue', (('rna_type', 'Struct'),)),
   ('ID',
    (('asset_data', 'AssetMetaData'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('Image',
    (('asset_data', 'AssetMetaData'),
     ('colorspace_settings', 'ColorManagedInputColorspaceSettings'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('packed_file', 'PackedFile'),
     ('packed_files', 'ImagePackedFile'),
     ('preview', 'ImagePreview'),
     ('render_slots', 'RenderSlot'),
     ('rna_type', 'Struct'),
     ('stereo_3d_format', 'Stereo3dFormat'),
     ('tiles', 'UDIMTile'))),
   ('ImageUser', (('rna_type', 'Struct'),)),
   ('Int2Attribute', (('data', 'Int2AttributeValue'), ('rna_type', 'Struct'))),
   ('Int2AttributeValue', (('rna_type', 'Struct'),)),
   ('IntAttribute', (('data', 'IntAttributeValue'), ('rna_type', 'Struct'))),
   ('IntAttributeValue', (('rna_type', 'Struct'),)),
   ('Material',
    (('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('cycles', 'CyclesMaterialSettings'),
     ('grease_pencil', 'MaterialGPencilStyle'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('lineart', 'MaterialLineArt'),
     ('node_tree', 'NodeTree'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'),
     ('texture_paint_images', 'Image'),
     ('texture_paint_slots', 'TexPaintSlot'))),
   ('MaterialSlot', (('material', 'Material'), ('rna_type', 'Struct'))),
   ('Mesh',
    (('animation_data', 'AnimData'),
     ('asset_data', 'AssetMetaData'),
     ('attributes', 'Attribute'),
     ('color_attributes', 'Attribute'),
     ('corner_normals', 'MeshNormalValue'),
     ('cycles', 'CyclesMeshSettings'),
     ('edges', 'MeshEdge'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('loop_triangle_polygons', 'ReadOnlyInteger'),
     ('loop_triangles', 'MeshLoopTriangle'),
     ('loops', 'MeshLoop'),
     ('materials', 'Material'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('polygon_normals', 'MeshNormalValue'),
     ('polygons', 'MeshPolygon'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'),
     ('shape_keys', 'Key'),
     ('skin_vertices', 'MeshSkinVertexLayer'),
     ('texco_mesh', 'Mesh'),
     ('texture_mesh', 'Mesh'),
     ('uv_layer_clone', 'MeshUVLoopLayer'),
     ('uv_layer_stencil', 'MeshUVLoopLayer'),
     ('uv_layers', 'MeshUVLoopLayer'),
     ('vertex_colors', 'MeshLoopColorLayer'),
     ('vertex_normals', 'MeshNormalValue'),
     ('vertices', 'MeshVertex'))),
   ('MeshEdge', (('rna_type', 'Struct'),)),
   ('MeshLoop', (('rna_type', 'Struct'),)),
   ('MeshPolygon', (('rna_type', 'Struct'),)),
   ('MeshUVLoop', (('rna_type', 'Struct'),)),
   ('MeshUVLoopLayer',
    (('data', 'MeshUVLoop'),
     ('pin', 'BoolAttributeValue'),
     ('rna_type', 'Struct'),
     ('uv', 'Float2AttributeValue'))),
   ('MeshVertex', (('groups', 'VertexGroupElement'), ('rna_type', 'Struct'))),
   ('Node',
    (('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('panel_states', 'NodePanelState'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'))),
   ('NodeLink',
    (('from_node', 'Node'),
     ('from_socket', 'NodeSocket'),
     ('rna_type', 'Struct'),
     ('to_node', 'Node'),
     ('to_socket', 'NodeSocket'))),
   ('NodePanelState', (('rna_type', 'Struct'),)),
   ('NodeSocket', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketBool', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketColor', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloat', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatAngle', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatDistance', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatFactor', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatUnsigned', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketFloatWavelength', (('rna_type', 'Struct'), ('node', 'Node'))),
   ('NodeSocketInt', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketShader', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeSocketVector', (('node', 'Node'), ('rna_type', 'Struct'))),
   ('NodeTree',
    (('animation_data', 'AnimData'),
     ('annotation', 'Annotation'),
     ('asset_data', 'AssetMetaData'),
     ('interface', 'NodeTreeInterface'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('links', 'NodeLink'),
     ('nodes', 'Node'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('Object',
    (('active_material', 'Material'),
     ('active_shape_key', 'ShapeKey'),
     ('animation_data', 'AnimData'),
     ('animation_visualization', 'AnimViz'),
     ('asset_data', 'AssetMetaData'),
     ('collision', 'CollisionSettings'),
     ('constraints', 'Constraint'),
     ('cycles', 'CyclesObjectSettings'),
     ('data', 'ID'),
     ('display', 'ObjectDisplay'),
     ('field', 'FieldSettings'),
     ('image_user', 'ImageUser'),
     ('instance_collection', 'Collection'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('light_linking', 'ObjectLightLinking'),
     ('lineart', 'ObjectLineArt'),
     ('material_slots', 'MaterialSlot'),
     ('modifiers', 'Modifier'),
     ('motion_path', 'MotionPath'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('parent', 'Object'),
     ('particle_systems', 'ParticleSystem'),
     ('pose', 'Pose'),
     ('preview', 'ImagePreview'),
     ('rigid_body', 'RigidBodyObject'),
     ('rigid_body_constraint', 'RigidBodyConstraint'),
     ('rna_type', 'Struct'),
     ('selection_sets', 'SelectionSet'),
     ('shader_effects', 'ShaderFx'),
     ('soft_body', 'SoftBodySettings'),
     ('vertex_groups', 'VertexGroup'))),
   ('PackedFile', (('rna_type', 'Struct'),)),
   ('PropertyGroup', (('rna_type', 'Struct'),)),
   ('Scene',
    (('active_clip', 'MovieClip'),
     ('animation_data', 'AnimData'),
     ('annotation', 'Annotation'),
     ('asset_data', 'AssetMetaData'),
     ('background_set', 'Scene'),
     ('camera', 'Object'),
     ('collection', 'Collection'),
     ('compositing_node_group', 'NodeTree'),
     ('cursor', 'View3DCursor'),
     ('cycles', 'CyclesRenderSettings'),
     ('cycles_curves', 'CyclesCurveRenderSettings'),
     ('display', 'SceneDisplay'),
     ('display_settings', 'ColorManagedDisplaySettings'),
     ('eevee', 'SceneEEVEE'),
     ('grease_pencil_settings', 'SceneGpencil'),
     ('hydra', 'SceneHydra'),
     ('keying_sets', 'KeyingSet'),
     ('keying_sets_all', 'KeyingSet'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('objects', 'Object'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('render', 'RenderSettings'),
     ('rigidbody_world', 'RigidBodyWorld'),
     ('rna_type', 'Struct'),
     ('safe_areas', 'DisplaySafeAreas'),
     ('sequence_editor', 'SequenceEditor'),
     ('sequencer_colorspace_settings', 'ColorManagedSequencerColorspaceSettings'),
     ('timeline_markers', 'TimelineMarker'),
     ('tool_settings', 'ToolSettings'),
     ('transform_orientation_slots', 'TransformOrientationSlot'),
     ('unit_settings', 'UnitSettings'),
     ('view_layers', 'ViewLayer'),
     ('view_settings', 'ColorManagedViewSettings'),
     ('world', 'World'))),
   ('ShaderNodeBsdfPrincipled',
    (('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('panel_states', 'NodePanelState'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'))),
   ('ShaderNodeOutputMaterial',
    (('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('panel_states', 'NodePanelState'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'))),
   ('ShaderNodeTexImage',
    (('color_mapping', 'ColorMapping'),
     ('image', 'Image'),
     ('image_user', 'ImageUser'),
     ('inputs', 'NodeSocket'),
     ('internal_links', 'NodeLink'),
     ('outputs', 'NodeSocket'),
     ('panel_states', 'NodePanelState'),
     ('parent', 'Node'),
     ('rna_type', 'Struct'),
     ('texture_mapping', 'TexMapping'))),
   ('ShaderNodeTree',
    (('animation_data', 'AnimData'),
     ('annotation', 'Annotation'),
     ('asset_data', 'AssetMetaData'),
     ('interface', 'NodeTreeInterface'),
     ('library', 'Library'),
     ('library_weak_reference', 'LibraryWeakReference'),
     ('links', 'NodeLink'),
     ('nodes', 'Node'),
     ('original', 'ID'),
     ('override_library', 'IDOverrideLibrary'),
     ('preview', 'ImagePreview'),
     ('rna_type', 'Struct'))),
   ('TexMapping', (('rna_type', 'Struct'),)),
   ('UVLoopLayers',
    (('active', 'MeshUVLoopLayer'), ('active_render', 'MeshUVLoopLayer'), ('rna_type', 'Struct'))))))
_FRAMEWORK_CLASSES = ("Struct", "Property", "Function", "BoolProperty", "IntProperty", "FloatProperty",
                      "StringProperty", "EnumProperty", "PointerProperty", "CollectionProperty", "PropertyGroup")
_PROPERTY_FRAMEWORK = frozenset({"Property", "BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                                 "EnumProperty", "PointerProperty", "CollectionProperty"})
_REGISTERED_TARGETS = {("Material", "cycles"): "CyclesMaterialSettings", ("Mesh", "cycles"): "CyclesMeshSettings",
                       ("Object", "cycles"): "CyclesObjectSettings", ("Object", "selection_sets"): "SelectionSet",
                       ("Scene", "cycles"): "CyclesRenderSettings", ("Scene", "cycles_curves"): "CyclesCurveRenderSettings"}
_RUNTIME_MARKER_ROWS = ((('Material', 'cycles'), ('POINTER', True, True, False, None, None)),
 (('Mesh', 'cycles'), ('POINTER', True, True, False, None, None)),
 (('Object', 'cycles'), ('POINTER', True, True, False, None, None)),
 (('Object', 'selection_sets'), ('COLLECTION', True, True, False, None, None)),
 (('Object', 'active_selection_set'), ('INT', False, True, False, 0, None)),
 (('Scene', 'cycles'), ('POINTER', True, True, False, None, None)),
 (('Scene', 'cycles_curves'), ('POINTER', True, True, False, None, None)))
_TYPE_DICT = type.__dict__["__dict__"]
_TYPE_MRO = type.__dict__["__mro__"]
_TYPE_NAME = type.__dict__["__name__"]
_TYPE_GET = type.__dict__["__getattribute__"]
_TYPE_CALL = type.__dict__["__call__"]


def refused(reason: str) -> BridgeError:
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Current-pixel graph is outside its qualified finite profile.",
                       {"reason": reason, "scope_complete": False, "recovery_authorized": False})


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _text(value: Any, maximum: int = 63, *, blank: bool = False) -> str:
    if type(value) is not str or len(value) > maximum or (not blank and not value.strip()):
        raise refused("TEXT_SHAPE_OR_BUDGET")
    try:
        if len(value.encode("utf-8")) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise refused("TEXT_ENCODING_OR_BUDGET")
    except UnicodeError as cause:
        raise refused("TEXT_ENCODING_OR_BUDGET") from cause
    return value


def _int(value: Any, maximum: int, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise refused("INTEGER_SHAPE_OR_BUDGET")
    return value


def _bool(value: Any) -> bool:
    if type(value) is not bool:
        raise refused("BOOLEAN_SHAPE")
    return value


def _bounded(values: Any, maximum: int) -> tuple[Any, ...]:
    result = tuple(islice(values, maximum + 1))
    if len(result) > maximum:
        raise refused("COLLECTION_BUDGET")
    return result


def _float(value: Any) -> str:
    if type(value) is not float or not math.isfinite(value):
        raise refused("NONFINITE_OR_NON_NATIVE_FLOAT")
    try:
        raw = struct.pack("<f", value)
        if struct.pack("<d", struct.unpack("<f", raw)[0]) != struct.pack("<d", value):
            raise refused("NON_FLOAT32_NATIVE_VALUE")
    except (OverflowError, struct.error) as cause:
        raise refused("NON_FLOAT32_NATIVE_VALUE") from cause
    return raw.hex()


def _vector(value: Any, size: int) -> list[str]:
    values = _bounded(value, size)
    if len(values) != size:
        raise refused("NATIVE_VECTOR_SHAPE")
    return [_float(item) for item in values]


def property_metadata(prop: Any, *, fixed_types: bool = True) -> dict[str, Any]:
    """Class metadata only; numeric-only array metadata has a real declaration."""
    kind = prop.type
    if kind not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM", "POINTER", "COLLECTION"}:
        raise refused("RNA_PROPERTY_TYPE")
    fixed = prop.fixed_type if fixed_types and kind in {"POINTER", "COLLECTION"} else None
    return {"identifier": _text(prop.identifier, 128), "type": kind,
            "readonly": _bool(prop.is_readonly), "runtime": _bool(prop.is_runtime),
            "registered": _bool(prop.is_registered),
            "array_length": _int(prop.array_length, 1_048_576) if kind in {"BOOLEAN", "INT", "FLOAT"} else None,
            "fixed_type": None if fixed is None else _text(fixed.identifier, 128),
            "enum_flag": _bool(prop.is_enum_flag) if kind == "ENUM" else None}


def catalog_census(types: Any, build_hash: bytes) -> dict[str, Any]:
    """Bounded class-only census for root's isolated metadata fixture."""
    if type(build_hash) is not bytes or build_hash not in BUILDS:
        raise refused("OFFICIAL_BUILD_REQUIRED")
    classes = {}
    for name in CENSUS_TYPES:
        native = getattr(types, name, None)
        if native is None:
            classes[name] = {"present": False}
            continue
        rna = native.bl_rna
        properties = [property_metadata(prop) for prop in _bounded(rna.properties, 512)]
        if len({row["identifier"] for row in properties}) != len(properties):
            raise refused("DUPLICATE_RNA_PROPERTY")
        row = {"present": True, "identifier": _text(rna.identifier, 128),
               "base": None if rna.base is None else _text(rna.base.identifier, 128),
               "properties": properties,
               "functions": [_text(fn.identifier, 128) for fn in _bounded(rna.functions, 128)]}
        row["sha256"] = hashlib.sha256(_canonical(row)).hexdigest()
        classes[name] = row
    methods = {}
    for kind, name in (("ID", "as_pointer"), ("bpy_struct", "is_property_set")):
        owner = getattr(types, kind, None)
        descriptor = None if owner is None else getattr_static(owner, name, None)
        canonical_kind = type(descriptor) in {MethodDescriptorType, WrapperDescriptorType}
        methods[kind + "." + name] = {"present": descriptor is not None,
                    "descriptor_type": type(descriptor).__name__,
                    "declaring_class": descriptor.__objclass__.__name__ if canonical_kind else None,
                    "native_descriptor": canonical_kind}
    result = {"schema": "current_pixels_complete_class_census_v1", "build_hash": build_hash.decode("ascii"),
              "classes": classes, "methods": methods,
              "scope": "class descriptors only; no defaults, ID values or hidden-state proof"}
    if len(_canonical(result)) > 2 * 1024 * 1024:
        raise refused("RNA_CENSUS_REPORT_BUDGET")
    return result


def _class_dict(cls: Any) -> Any:
    try:
        return _TYPE_DICT.__get__(cls, type(cls))
    except TypeError as cause:
        raise refused("NATIVE_CLASS_REQUIRED") from cause


def _class_mro(cls: Any) -> tuple[Any, ...]:
    try:
        chain = _TYPE_MRO.__get__(cls, type(cls))
    except TypeError as cause:
        raise refused("NATIVE_CLASS_MRO_REQUIRED") from cause
    if type(chain) is not tuple or not 1 <= len(chain) <= 32:
        raise refused("NATIVE_CLASS_MRO_BUDGET")
    return chain


def _class_find(cls: Any, name: str) -> Any:
    for parent in _class_mro(cls):
        value = _class_dict(parent).get(name)
        if value is not None:
            return value
    return None


def _native_metaclasses(bpy: Any) -> tuple[Any, Any]:
    native = bpy.types.bpy_struct_meta_idprop
    if type(native) is not type:
        raise refused("NATIVE_METACLASS_REQUIRED")
    chain = _class_mro(native)
    setter = _class_find(native, "__setattr__")
    if (len(chain) != 3 or any(actual is not expected for actual, expected in zip(chain, (native, type, object), strict=True))
            or _TYPE_NAME.__get__(native, type) != "bpy_struct_meta_idprop"
            or type(setter) is not WrapperDescriptorType or setter.__objclass__ is not native
            or _class_find(native, "__getattribute__") is not _TYPE_GET
            or _class_find(native, "__call__") is not _TYPE_CALL or _class_find(native, "__getattr__") is not None):
        raise refused("NATIVE_METACLASS_ORIGIN_CHANGED")
    return type(bpy.types.PropertyGroup), native


def _metaclass(cls: Any, registered: Any, native: Any) -> None:
    meta = type(cls)
    if ((meta is not type and meta is not registered and meta is not native)
            or _class_find(meta, "__getattribute__") is not _TYPE_GET
            or _class_find(meta, "__call__") is not _TYPE_CALL or _class_find(meta, "__getattr__") is not None):
        raise refused("UNQUALIFIED_CLASS_METACLASS")


def _unshadowed(cls: Any, fields: tuple[str, ...]) -> None:
    chain = _class_mro(cls)
    for name in fields:
        descriptor = _class_find(cls, name)
        if descriptor is not None and (type(descriptor) not in (GetSetDescriptorType, MemberDescriptorType)
                                       or not any(descriptor.__objclass__ is parent for parent in chain)):
            raise refused("NATIVE_FIELD_PYTHON_SHADOW:" + name)


def _constructor_proof(bpy: Any, name: str, resolved: Any = None) -> tuple[Any, ...]:
    """Constructor-only closure under the canonical stock registry assumption.

    This checks finite reachable classes, never creates a target instance or
    recursively projects its values. It does not defend arbitrary C extensions
    rewriting a native declaration while retaining its static signature.
    """
    registered, native = _native_metaclasses(bpy)
    base = bpy.types.bpy_struct
    _metaclass(base, registered, native)
    if _class_find(base, "__del__") is not None:
        raise refused("NATIVE_CONSTRUCTOR_FINALIZER_UNQUALIFIED")
    getter, pointer = _class_find(base, "__getattribute__"), _class_find(base, "as_pointer")
    constructor, initializer = _class_find(base, "__new__"), _class_find(base, "__init__")
    if (type(getter) is not WrapperDescriptorType or getter.__objclass__ is not base
            or type(pointer) is not MethodDescriptorType or pointer.__objclass__ is not base
            or type(constructor) is not BuiltinFunctionType or type(initializer) is not WrapperDescriptorType
            or not any(initializer.__objclass__ is owner for owner in (base, object))):
        raise refused("NATIVE_CONSTRUCTOR_GETTER_OR_POINTER_CHANGED")
    struct_class = bpy.types.Struct
    canonical = getattr(bpy.types, name, None) if resolved is None else resolved
    if canonical is None:
        raise refused("REQUIRED_CONSTRUCTOR_MISSING:" + name)
    for cls in (struct_class, canonical):
        _metaclass(cls, registered, native)
        if (not any(parent is base for parent in _class_mro(cls))
                or _class_find(cls, "__getattribute__") is not getter or _class_find(cls, "as_pointer") is not pointer
                or _class_find(cls, "__new__") is not constructor or _class_find(cls, "__init__") is not initializer
                or _class_find(cls, "__getattr__") is not None or _class_find(cls, "__del__") is not None):
            raise refused("NATIVE_CONSTRUCTOR_ORIGIN_CHANGED:" + name)
    _unshadowed(struct_class, ("identifier", "properties", "functions", "base"))
    _unshadowed(canonical, ("identifier", "properties", "functions", "base"))
    if name in _PROPERTY_FRAMEWORK:
        _unshadowed(canonical, ("identifier", "type", "is_readonly", "is_runtime", "is_registered",
                                "array_length", "fixed_type", "is_enum_flag"))
    rna = _class_dict(canonical).get("bl_rna")
    if (type(rna) is not struct_class or getter(rna, "identifier") != name
            or type(pointer(rna)) is not int or not 0 < pointer(rna) < 2**64):
        raise refused("NATIVE_OWN_STRUCT_IDENTITY_CHANGED:" + name)
    return canonical, rna, getter, pointer, (base, registered, native, getter, pointer, constructor, initializer)


def _registered_target(bpy: Any, name: str, check: Callable[[], None]) -> tuple[Any, ...]:
    group_proof = _constructor_proof(bpy, "PropertyGroup")
    group, _rna, _getter, _pointer, _origin = group_proof
    base = bpy.types.bpy_struct
    descriptor = _class_find(base, "bl_rna_get_subclass_py")
    if (type(descriptor) is not ClassMethodDescriptorType or descriptor.__objclass__ is not base
            or descriptor.__name__ != "bl_rna_get_subclass_py"
            or _class_find(group, "bl_rna_get_subclass_py") is not descriptor):
        raise refused("REGISTERED_LOOKUP_DESCRIPTOR_CHANGED")
    bound = descriptor.__get__(None, group)
    if type(bound) is not BuiltinFunctionType or bound.__self__ is not group:
        raise refused("REGISTERED_LOOKUP_BINDING_CHANGED")
    check()
    target = bound(name, None)
    check()
    if (_constructor_proof(bpy, "PropertyGroup")[0] is not group
            or bpy.types.bpy_struct is not base or _class_find(base, "bl_rna_get_subclass_py") is not descriptor
            or _class_find(group, "bl_rna_get_subclass_py") is not descriptor):
        raise refused("REGISTERED_LOOKUP_ORIGIN_CHANGED")
    if target is None:
        raise refused("REGISTERED_TARGET_MISSING:" + name)
    return _constructor_proof(bpy, name, target)


def _deferred_type(bpy: Any) -> tuple[Any, tuple[Any, ...]]:
    """Exact source-pinned non-descriptor marker; never its stored values."""
    namespace = ModuleType.__getattribute__(bpy, "__dict__") if type(bpy) is ModuleType else {}
    props = namespace.get("props")
    exports = ModuleType.__getattribute__(props, "__dict__") if type(props) is ModuleType else {}
    cls = exports.get("_PropertyDeferred")
    if type(cls) is not type:
        raise refused("NATIVE_RUNTIME_MARKER_ALIAS_REQUIRED")
    chain = _class_mro(cls)
    call = _class_find(cls, "__call__")
    getsets = tuple(_class_find(cls, name) for name in ("function", "keywords"))
    if (len(chain) != 2 or chain[0] is not cls or chain[1] is not object
            or _TYPE_NAME.__get__(cls, type) != "_PropertyDeferred"
            or _class_find(cls, "__getattribute__") is not object.__getattribute__
            or _class_find(cls, "__setattr__") is not object.__setattr__
            or any(_class_find(cls, name) is not None for name in ("__getattr__", "__get__", "__set__", "__delete__"))
            or type(call) is not WrapperDescriptorType or call.__objclass__ is not cls
            or any(type(slot) is not GetSetDescriptorType or slot.__objclass__ is not cls for slot in getsets)):
        raise refused("NATIVE_RUNTIME_MARKER_SLOTS_CHANGED")
    build = bpy.app.build_hash
    if type(build) is not bytes or build not in BUILDS:
        raise refused("OFFICIAL_BUILD_REQUIRED")
    # Retain references, not bare addresses: replacement cannot reuse an
    # expired marker/module/slot identity while these observations are alive.
    return cls, (bpy, props, cls, chain, call, getsets, object.__getattribute__, object.__setattr__, build)


def _runtime_marker_origins(bpy: Any, canonical: Any, kind: str,
                            rows: list[dict[str, Any]]) -> tuple[Any, ...]:
    """Only seven exact existing runtime rows may carry inert native markers."""
    namespace = ModuleType.__getattribute__(bpy, "__dict__") if type(bpy) is ModuleType else {}
    props = namespace.get("props")
    exports = ModuleType.__getattribute__(props, "__dict__") if type(props) is ModuleType else {}
    exported = exports.get("_PropertyDeferred")
    seen, origins = set(), []
    for row in rows:
        if not row["runtime"]:
            continue
        name = row["identifier"]
        shape = tuple(row[key] for key in ("type", "readonly", "runtime", "registered", "array_length", "enum_flag"))
        if name in seen or _pin_get(_RUNTIME_MARKER_ROWS, (kind, name), None, "marker") != shape:
            raise refused("UNQUALIFIED_RUNTIME_MARKER_DECLARATION")
        seen.add(name)
        if sum(other["identifier"] == name for other in rows) != 1:
            raise refused("DUPLICATE_RUNTIME_MARKER_DECLARATION")
        marker = _class_find(canonical, name)
        if marker is None or type(marker) is not exported:
            continue  # No exemption: generic native-field guard still applies.
        cls, origin = _deferred_type(bpy)
        if type(marker) is not cls:
            raise refused("NATIVE_RUNTIME_MARKER_ALIAS_CHANGED")
        origins.append((name, marker, origin, shape))
    return tuple(origins)


def _same_markers(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right, strict=True):
        if a[0] != b[0] or a[1] is not b[1] or a[3] != b[3]:
            return False
        x, y = a[2], b[2]
        if (any(x[index] is not y[index] for index in (0, 1, 2, 4, 6, 7)) or x[8] != y[8]
                or len(x[3]) != len(y[3]) or any(p is not q for p, q in zip(x[3], y[3], strict=True))
                or len(x[5]) != len(y[5]) or any(p is not q for p, q in zip(x[5], y[5], strict=True))):
            return False
    return True


def _same_constructor(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    return (len(left) == len(right) == 5 and all(a is b for a, b in zip(left[:4], right[:4], strict=True))
            and len(left[4]) == len(right[4]) and all(a is b for a, b in zip(left[4], right[4], strict=True)))


class _Reader:
    def __init__(self, bpy: Any, check: Callable[[], None]):
        if threading.current_thread() is not threading.main_thread():
            raise refused("BLENDER_MAIN_THREAD_REQUIRED")
        self.bpy, self.check = bpy, check
        check()
        self.build = bpy.app.build_hash
        if (type(self.build) is not bytes or self.build not in BUILDS
                or tuple(bpy.app.version) != BUILDS[self.build]):
            raise refused("OFFICIAL_BUILD_REQUIRED")
        self.catalogs: dict[str, str] = {}
        self._class_cache: dict[str, tuple[Any, ...]] = {}
        self._constructors: dict[str, tuple[Any, ...]] = {}
        self._leaf_origins: dict[tuple[str, int, str, str], Any] = {}
        self._framework_ready = False
        self.registered_query_gate_present = True

    def _constructor(self, name: str) -> tuple[Any, ...]:
        proof = self._constructors.get(name)
        if proof is None:
            self.check()
            proof = _constructor_proof(self.bpy, name)
            self.check()
            self._constructors[name] = proof
        return proof

    def _framework(self) -> None:
        if not self._framework_ready:
            for name in _FRAMEWORK_CLASSES:
                self._constructor(name)
            self._framework_ready = True

    def class_catalog(self, kind: str) -> tuple[Any, ...]:
        self.check()
        canonical = getattr(self.bpy.types, kind, None)
        if canonical is None:
            raise refused("EXACT_RNA_CLASS_REQUIRED")
        self._framework()
        proof = self._constructor(kind)
        if proof[0] is not canonical:
            raise refused("CLASS_CONSTRUCTOR_BINDING_CHANGED")
        rna = proof[1]
        pointer = _int(rna.as_pointer(), 2**64 - 1, minimum=1)
        cached = self._class_cache.get(kind)
        if cached is not None:
            if cached[0] is not canonical or cached[1] != pointer or not _same_constructor(cached[5], proof):
                raise refused("RNA_CLASS_CHANGED_WITHIN_PASS")
            markers = _runtime_marker_origins(self.bpy, canonical, kind, cached[4])
            if not _same_markers(markers, cached[3]):
                raise refused("RUNTIME_MARKER_CHANGED_WITHIN_PASS")
            exempt = {origin[0] for origin in markers}
            _unshadowed(canonical, tuple(row["identifier"] for row in cached[4] if row["identifier"] not in exempt))
            return cached[2]
        if rna.identifier != kind:
            raise refused("EXACT_RNA_CATALOG_REQUIRED")
        props = _bounded(rna.properties, 512)
        rows = [property_metadata(prop, fixed_types=False) for prop in props]
        if len({row["identifier"] for row in rows}) != len(rows):
            raise refused("DUPLICATE_RNA_PROPERTY")
        row = {"present": True, "identifier": kind,
               "base": None if rna.base is None else _text(rna.base.identifier, 128),
               "properties": rows,
               "functions": [_text(fn.identifier, 128) for fn in _bounded(rna.functions, 128)]}
        static_digest = hashlib.sha256(_canonical(row)).hexdigest()
        if _pin_get(_pin_get(_STATIC_CATALOG_HASHES, self.build, None, "rows"), kind) != static_digest:
            raise refused("UNQUALIFIED_STATIC_RNA_CATALOG:" + kind)
        property_pointers = tuple(_int(prop.as_pointer(), 2**64 - 1, minimum=1) for prop in props)
        markers = _runtime_marker_origins(self.bpy, canonical, kind, rows)
        exempt = {origin[0] for origin in markers}
        _unshadowed(canonical, tuple(metadata["identifier"] for metadata in rows if metadata["identifier"] not in exempt))
        targets = _pin_get(_pin_get(_FIXED_TARGETS, self.build, None, "rows"), kind, (), "rows")
        for metadata in rows:
            target = _pin_get(targets, metadata["identifier"])
            if target is None:
                continue
            if metadata["runtime"]:
                if _REGISTERED_TARGETS.get((kind, metadata["identifier"])) != target:
                    raise refused("UNMAPPED_REGISTERED_TARGET")
                if not self.registered_query_gate_present:
                    raise refused("REGISTERED_LOOKUP_REQUIRES_PURE_ORIGIN_GATE")
                self._constructors[target] = _registered_target(self.bpy, target, self.check)
            else:
                self._constructor(target)
        rows = [property_metadata(prop) for prop in props]
        for metadata in rows:
            if metadata["fixed_type"] != _pin_get(targets, metadata["identifier"]):
                raise refused("FIXED_TYPE_DECLARATION_CHANGED")
        row["properties"] = rows
        digest = hashlib.sha256(_canonical(row)).hexdigest()
        if _pin_get(_pin_get(_CATALOG_HASHES, self.build, None, "rows"), kind) != digest:
            raise refused("UNQUALIFIED_RNA_CATALOG:" + kind)
        # Native registered-target lookups are the only native recursion in
        # this metadata pass. Re-read schema and raw origins afterward rather
        # than accepting a changed marker/catalog as a replacement baseline.
        current_proof = _constructor_proof(self.bpy, kind)
        current_props = _bounded(rna.properties, 512)
        current_rows = [property_metadata(prop, fixed_types=False) for prop in current_props]
        current_row = {"present": True, "identifier": _text(rna.identifier, 128),
                       "base": None if rna.base is None else _text(rna.base.identifier, 128),
                       "properties": current_rows,
                       "functions": [_text(fn.identifier, 128) for fn in _bounded(rna.functions, 128)]}
        current_markers = _runtime_marker_origins(self.bpy, canonical, kind, current_rows)
        if (getattr(self.bpy.types, kind, None) is not canonical or not _same_constructor(proof, current_proof)
                or tuple(_int(prop.as_pointer(), 2**64 - 1, minimum=1) for prop in current_props) != property_pointers
                or hashlib.sha256(_canonical(current_row)).hexdigest() != static_digest
                or not _same_markers(markers, current_markers)):
            raise refused("RNA_MARKER_OR_SCHEMA_CHANGED_DURING_QUALIFICATION")
        current_exempt = {origin[0] for origin in current_markers}
        _unshadowed(canonical, tuple(metadata["identifier"] for metadata in current_rows if metadata["identifier"] not in current_exempt))
        self.catalogs[kind] = digest
        # props/markers/proof retain strong references for this synchronous
        # pass; no marker function/keywords or owner runtime values are read.
        self._class_cache[kind] = canonical, pointer, props, markers, current_rows, proof
        return props

    def catalog(self, owner: Any, kind: str) -> tuple[Any, ...]:
        canonical = getattr(self.bpy.types, kind, None)
        if canonical is None or type(owner) is not canonical:
            raise refused("EXACT_RNA_CLASS_REQUIRED")
        props = self.class_catalog(kind)
        if owner.bl_rna.as_pointer() != canonical.bl_rna.as_pointer():
            raise refused("EXACT_RNA_CATALOG_REQUIRED")
        return props

    def begin_pass(self) -> None:
        self.check()
        # A synchronous live pass has no foreign/provider callbacks. Re-census
        # every used class after pure-work yields, before any descendant read.
        self._class_cache.clear()
        self._constructors.clear()
        self._leaf_origins.clear()
        self._framework_ready = False

    def local_id(self, owner: Any, kind: str) -> dict[str, Any]:
        self.catalog(owner, kind)
        if owner.library is not None or owner.override_library is not None or owner.is_editable is not True:
            raise refused("LINKED_OVERRIDE_OR_READONLY_ID")
        pointer = _int(owner.as_pointer(), 2**64 - 1, minimum=1)
        uid = _int(owner.session_uid, 2**64 - 1, minimum=1)
        return {"kind": "NodeTree" if kind == "ShaderNodeTree" else kind,
                "name": _text(owner.name), "pointer": format(pointer, "x"), "session_uid": str(uid)}

    def no_animation(self, owner: Any, kind: str) -> None:
        props = self.catalog(owner, kind)
        names = {prop.identifier for prop in props}
        if kind == "Image":
            if "animation_data" in names:
                raise refused("IMAGE_ANIMATION_SCHEMA_UNQUALIFIED")
        elif "animation_data" in names and owner.animation_data is not None:
            raise refused("ANIMATED_CONSUMER")


def _names(image_name: Any, snapshot_name: Any, materials: Any) -> tuple[str | None, str, tuple[str, ...]]:
    if image_name is not None:
        image_name = _text(image_name)
    snapshot_name = _text(snapshot_name)
    if type(materials) not in {tuple, list} or not 1 <= len(materials) <= 2:
        raise invalid_argument("Declare one or two exact affected Materials.")
    names = tuple(_text(value) for value in materials)
    if len(set(names)) != len(names):
        raise invalid_argument("Declared Material names must be unique.")
    return image_name, snapshot_name, names


def _identity_scope(reader: _Reader, image_name: str | None, snapshot_name: str,
                    materials: tuple[str, ...]) -> tuple[Any, Any, tuple[Any, ...], dict[str, Any]]:
    from .tools.image_portability import OWNER_KEY

    bpy = reader.bpy
    reader.check()
    helper = bpy.data.images.get(snapshot_name)
    if helper is None:
        raise refused("SNAPSHOT_MISSING")
    helper_id = reader.local_id(helper, "Image")
    if helper.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")
    original = helper.get(OWNER_KEY)
    if original is None:
        raise refused("NATIVE_OWNER_MISSING")
    original_id = reader.local_id(original, "Image")
    if (original is helper or bpy.data.images.get(original_id["name"]) is not original
            or (image_name is not None and bpy.data.images.get(image_name) is not original)):
        raise refused("NATIVE_OWNER_CHANGED_OR_AMBIGUOUS")
    if original.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")
    rows, owners = [], []
    for name in sorted(materials):
        reader.check()
        material = bpy.data.materials.get(name)
        if material is None:
            raise refused("DECLARED_MATERIAL_MISSING")
        row = reader.local_id(material, "Material")
        tree = material.node_tree
        if tree is None:
            raise refused("EMBEDDED_MATERIAL_TREE_REQUIRED")
        row["tree"] = reader.local_id(tree, "ShaderNodeTree")
        rows.append(row)
        owners.append(material)
    return original, helper, tuple(owners), {"schema": "current_pixels_identity_v1", "profile": PROFILE,
                "original": original_id, "snapshot": helper_id, "native_owner": original_id,
                "original_loaded": True, "snapshot_loaded": True, "materials": rows}


def identity_witness(bpy: Any, image_name: str | None, snapshot_name: str,
                     affected_materials: tuple[str, ...] | list[str], *,
                     check: Callable[[], None] | None = None) -> dict[str, Any]:
    """Pre-grant IDs only: never size/is_float/pixels/packed data or a file probe."""
    names = _names(image_name, snapshot_name, affected_materials)
    reader = _Reader(bpy, (lambda: None) if check is None else check)
    reader.registered_query_gate_present = check is not None
    return _identity_scope(reader, *names)[3]


def validate_lifecycle_record(value: Any) -> str:
    """Canonical nonauthorizing helper record; native OWNER binds the Image."""
    raw = _text(value, 1024)
    def pairs(rows):
        result = {}
        for key, item in rows:
            if key in result:
                raise refused("LIFECYCLE_RECORD_DUPLICATE_KEYS")
            result[key] = item
        return result
    try:
        parsed = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as cause:
        raise refused("LIFECYCLE_RECORD_INVALID") from cause
    if (type(parsed) is not dict or set(parsed) != {"schema_version", "profile", "record_uuid", "runtime_nonce", "manifest_sha256"}
            or type(parsed["schema_version"]) is not int or parsed["schema_version"] != 1 or parsed["profile"] != PROFILE):
        raise refused("LIFECYCLE_RECORD_SCHEMA")
    for key, length in (("record_uuid", 32), ("runtime_nonce", 32), ("manifest_sha256", 64)):
        digest = parsed[key]
        if type(digest) is not str or len(digest) != length or any(c not in "0123456789abcdef" for c in digest):
            raise refused("LIFECYCLE_RECORD_DIGEST")
    if _canonical(parsed).decode("utf-8") != raw:
        raise refused("LIFECYCLE_RECORD_NONCANONICAL")
    return raw


def _runtime_absent(reader: _Reader, owner: Any, kind: str) -> None:
    """Inspect native storage presence, never a bundled pointer getter."""
    from .uv_edit_guard import _native_method_descriptor

    permitted = {"Object": {"cycles", "selection_sets", "active_selection_set"},
                 "Material": {"cycles"}, "Mesh": {"cycles"}}
    for prop in reader.catalog(owner, kind):
        if prop.is_runtime:
            if prop.identifier not in permitted.get(kind, set()):
                raise refused("UNQUALIFIED_RUNTIME_PROPERTY")
            if kind == "Mesh" and prop.identifier == "cycles":
                continue  # The separately reviewed Mesh policy handles raw 4.5 storage.
            method = _native_method_descriptor(reader.bpy.types.bpy_struct, type(owner))
            if method(owner, prop.identifier, ghost=False) is not False:
                raise refused("STORED_RUNTIME_PROPERTY_UNQUALIFIED")


def _pin_key(value: Any) -> bool:
    """Only exact native-independent literal keys may reach comparison/hash."""
    kind = type(value)
    if kind is str or kind is bytes:
        return len(value) <= 4096
    return kind is tuple and len(value) == 2 and all(type(part) is str and len(part) <= 4096 for part in value)

def _pin_get(table: Any, key: Any, default: Any = None, value_kind: str = "text") -> Any:
    """Lookup in literal tuple maps without a mutable alias or foreign dispatch.

    The source guard seals the recursively immutable original tuple by identity
    at every existing safe point. This reader neither caches RNA metadata nor
    substitutes that source proof for any native constructor/catalog check.
    """
    if type(table) is not tuple or not _pin_key(key):
        raise refused("IMMUTABLE_PIN_TABLE_SHAPE_CHANGED")
    if type(value_kind) is not str or value_kind not in {"text", "rows", "marker"}:
        raise refused("IMMUTABLE_PIN_TABLE_VALUE_KIND_CHANGED")
    if default is not None and (type(default) is not tuple or len(default)):
        raise refused("IMMUTABLE_PIN_TABLE_DEFAULT_CHANGED")
    if len(table) > 4096:
        raise refused("IMMUTABLE_PIN_TABLE_BUDGET")
    seen = set()
    for entry in table:
        if type(entry) is not tuple or len(entry) != 2:
            raise refused("IMMUTABLE_PIN_TABLE_ENTRY_CHANGED")
        candidate, value = entry
        if not _pin_key(candidate):
            raise refused("IMMUTABLE_PIN_TABLE_KEY_CHANGED")
        if candidate in seen:
            raise refused("IMMUTABLE_PIN_TABLE_DUPLICATE_KEY")
        seen.add(candidate)
        if type(value) is not str and type(value) is not tuple:
            raise refused("IMMUTABLE_PIN_TABLE_VALUE_CHANGED")
        if len(value) > 4096:
            raise refused("IMMUTABLE_PIN_TABLE_BUDGET")
        # Marker rows are terminal scalar tuples, unlike nested tuple maps.
        # Validate every part before their later tuple equality can run.
        if type(candidate) is tuple and (type(value) is not tuple or len(value) != 6
                or any(part is not None and type(part) is not str and type(part) is not bool and type(part) is not int for part in value)):
            raise refused("IMMUTABLE_PIN_MARKER_VALUE_CHANGED")
    for candidate, value in table:
        if type(candidate) is type(key) and candidate == key:
            if ((value_kind == "text" and type(value) is not str)
                    or (value_kind != "text" and type(value) is not tuple)):
                raise refused("IMMUTABLE_PIN_TABLE_VALUE_CHANGED")
            if value_kind == "marker" and (len(value) != 6
                    or any(part is not None and type(part) is not str and type(part) is not bool and type(part) is not int for part in value)):
                raise refused("IMMUTABLE_PIN_MARKER_VALUE_CHANGED")
            return value
    return default

def _keys_method(bpy: Any, cls: Any) -> Any:
    """Pin the stock USER-IDProperty query; never call an overridden method."""
    base = bpy.types.bpy_struct
    method = _class_find(base, "keys")
    if (type(method) is not MethodDescriptorType or method.__objclass__ is not base
            or _class_find(cls, "keys") is not method):
        raise refused("NATIVE_CUSTOM_KEYS_METHOD_CHANGED")
    return method

def _query_context(reader: _Reader) -> tuple[Any, ...]:
    """Bounded visible query footprint; not a full UI/selection witness."""
    bpy, context = reader.bpy, reader.bpy.context
    scene, window = context.scene, context.window
    return (bpy.data.as_pointer(), context.mode, scene.as_pointer(), scene.session_uid,
            context.view_layer.as_pointer(), scene.frame_current, scene.frame_subframe.hex(),
            None if window is None else (window.as_pointer(), window.scene.as_pointer(),
                window.workspace.as_pointer(), window.screen.as_pointer()))

def _user_count(reader: _Reader, owner: Any, target: Any, *, expected: int | None = None,
                reason: str = "NATIVE_REFERENCE_ROLES_CHANGED") -> int:
    reader.check()
    before = _query_context(reader)
    result = owner.user_of_id(target)
    reader.check()
    if _query_context(reader) != before:
        raise refused("NATIVE_REFERENCE_QUERY_CONTEXT_CHANGED")
    value = _int(result, 65536)
    if expected is not None and value != expected:
        error = refused(reason)
        error.context.update(expected_reference_count=expected, observed_reference_count=value)
        raise error
    return value

def _layer_field(reader: _Reader, owner: Any, kind: str, name: str, category: str, target: str) -> Any:
    """Only the three source-reviewed LayerCollection/ViewLayer relationships."""
    proof = reader._constructor(kind)
    canonical, rna = proof[:2]
    if type(owner) is not canonical or owner.bl_rna.as_pointer() != rna.as_pointer():
        raise refused("SCENE_LAYER_NATIVE_OWNER_REQUIRED")
    _unshadowed(canonical, (name,))
    prop = next((value for value in _bounded(rna.properties, 512) if value.identifier == name), None)
    if prop is None:
        raise refused("SCENE_LAYER_FIELD_REQUIRED")
    metadata = property_metadata(prop)
    if (metadata["type"] != category or metadata["fixed_type"] != target
            or metadata["runtime"] is not False or metadata["registered"] is not False):
        raise refused("SCENE_LAYER_FIELD_UNQUALIFIED")
    reader._constructor(target)
    reader.check()
    result = getattr(owner, name)
    _unshadowed(canonical, (name,))
    if not _same_constructor(proof, _constructor_proof(reader.bpy, kind)) or property_metadata(prop) != metadata:
        raise refused("SCENE_LAYER_FIELD_CHANGED")
    return result

def _scene_paths(reader: _Reader, scene: Any, root: Any, obj: Any) -> tuple[dict[Any, int], int]:
    """Count actual LayerCollection slots and Base memberships, not totals."""
    reader.check()
    before = _query_context(reader)
    paths: dict[Any, int] = {}
    memberships = 0
    for layer in _bounded(scene.view_layers, 16):
        top = _layer_field(reader, layer, "ViewLayer", "layer_collection", "POINTER", "LayerCollection")
        if _layer_field(reader, top, "LayerCollection", "collection", "POINTER", "Collection") is not root:
            raise refused("VIEW_LAYER_MASTER_COLLECTION_CHANGED")
        pending, seen = [top], set()
        while pending:
            item = pending.pop()
            pointer = _int(item.as_pointer(), 2**64 - 1, minimum=1)
            if pointer in seen or len(seen) >= 128:
                raise refused("SCENE_LAYER_PATH_BUDGET_OR_ALIAS")
            seen.add(pointer)
            collection = _layer_field(reader, item, "LayerCollection", "collection", "POINTER", "Collection")
            paths[collection] = paths.get(collection, 0) + 1
            children = _bounded(_layer_field(reader, item, "LayerCollection", "children", "COLLECTION", "LayerCollection"), 128)
            reader.check()
            if _query_context(reader) != before:
                raise refused("NATIVE_REFERENCE_QUERY_CONTEXT_CHANGED")
            pending.extend(children)
        bases = _bounded(_layer_field(reader, layer, "ViewLayer", "objects", "COLLECTION", "Object"), MAX_VERTICES)
        count = sum(owner is obj for owner in bases)
        if count > 1:
            raise refused("DUPLICATE_SCENE_OBJECT_BASE")
        memberships += count
    reader.check()
    if _query_context(reader) != before:
        raise refused("NATIVE_REFERENCE_QUERY_CONTEXT_CHANGED")
    return paths, memberships

def _rna_identity(reader: _Reader, owner: Any, kind: str, tree: Any,
                  retained: list[Any]) -> tuple[str, int, str, str]:
    """Identify a screened non-ID RNA leaf by native address and owning ID.

    Stock RNA may allocate a new Python wrapper for a returned PointerRNA.
    Neither Python identity nor its hash/equality proves the native identity.
    Keep the observed wrappers and ID owners alive for this bounded tree pass.
    """
    reader.catalog(owner, kind)
    _unshadowed(type(owner), ("id_data",))
    expected = reader.local_id(tree, "ShaderNodeTree")
    actual_owner = owner.id_data
    actual = reader.local_id(actual_owner, "ShaderNodeTree")
    if (actual["pointer"], actual["session_uid"]) != (expected["pointer"], expected["session_uid"]):
        raise refused("RNA_NATIVE_OWNER_CHANGED")
    pointer = _int(owner.as_pointer(), 2**64 - 1, minimum=1)
    retained.extend((owner, actual_owner))
    if len(retained) > 16 * MAX_SOCKETS:
        raise refused("RNA_IDENTITY_WITNESS_BUDGET")
    return kind, pointer, actual["pointer"], actual["session_uid"]

def _leaf_identity(reader: _Reader, owner: Any, allowed: frozenset[str], base: str,
                   tree: Any, retained: list[Any]) -> tuple[str, int, str, str]:
    """Normalize discrete base wrappers only against retained concrete roots.

    The pinned getter/SDNA declarations use Node/NodeSocket base pointer types
    with native refinement. Any exact base alias grants only address/owner
    identity against a retained concrete witness, never payload access.
    Initial graph collections must independently screen concrete classes first.
    """
    if type(owner) is getattr(reader.bpy.types, base, None):
        identity = _rna_identity(reader, owner, base, tree, retained)
        concrete = reader._leaf_origins.get(identity)
        if concrete is None:
            raise refused("RNA_BASE_ALIAS_NOT_RETAINED")
        actual = _rna_identity(reader, concrete, _kind(reader, concrete, allowed), tree, retained)
        if identity[1:] != actual[1:]:
            raise refused("RNA_RETAINED_CONCRETE_IDENTITY_CHANGED")
        return identity
    kind = _kind(reader, owner, allowed)
    actual = _rna_identity(reader, owner, kind, tree, retained)
    identity = base, actual[1], actual[2], actual[3]
    previous = reader._leaf_origins.get(identity)
    if previous is not None and type(previous) is not type(owner):
        raise refused("RNA_CONCRETE_IDENTITY_CLASS_CHANGED")
    if previous is None:
        if len(reader._leaf_origins) >= MAX_NODES + MAX_SOCKETS:
            raise refused("RNA_CONCRETE_IDENTITY_BUDGET")
        reader._leaf_origins[identity] = owner
    return identity

def _node_identity(reader: _Reader, node: Any, tree: Any,
                   retained: list[Any]) -> tuple[str, int, str, str]:
    return _leaf_identity(reader, node, NODES, "Node", tree, retained)

def _socket_identity(reader: _Reader, socket: Any, tree: Any,
                     retained: list[Any]) -> tuple[str, int, str, str]:
    return _leaf_identity(reader, socket, SOCKETS, "NodeSocket", tree, retained)

def _attribute_inventory(reader: _Reader, mesh: Any, counts: dict[str, int],
                          uv_names: tuple[str, ...]) -> tuple[Any, ...]:
    required = {"position": ("POINT", "FLOAT_VECTOR", "FloatVectorAttribute", "FloatVectorAttributeValue", counts["vertices"]),
                ".edge_verts": ("EDGE", "INT32_2D", "Int2Attribute", "Int2AttributeValue", counts["edges"]),
                ".corner_vert": ("CORNER", "INT", "IntAttribute", "IntAttributeValue", counts["loops"]),
                ".corner_edge": ("CORNER", "INT", "IntAttribute", "IntAttributeValue", counts["loops"])}
    allowed = dict(required)
    allowed["material_index"] = ("FACE", "INT", "IntAttribute", "IntAttributeValue", counts["polygons"])
    for name, domain, count in ((".select_vert", "POINT", "vertices"), (".hide_vert", "POINT", "vertices"),
                                (".select_edge", "EDGE", "edges"), (".hide_edge", "EDGE", "edges"),
                                ("uv_seam", "EDGE", "edges"), ("sharp_edge", "EDGE", "edges"),
                                (".select_poly", "FACE", "polygons"), (".hide_poly", "FACE", "polygons"),
                                ("sharp_face", "FACE", "polygons")):
        allowed[name] = (domain, "BOOLEAN", "BoolAttribute", "BoolAttributeValue", counts[count])
    uv, auxiliary = {}, {}
    for name in uv_names:
        uv[name] = ("CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue", counts["loops"])
        for prefix in ((".pn.", ".vs.", ".es.") if reader.build == b"62c1db4208e8" else (".pn.",)):
            auxiliary[prefix + name] = ("CORNER", "BOOLEAN", "BoolAttribute", "BoolAttributeValue", counts["loops"])
    if uv_names and reader.build == b"d13f752e3b9c":
        for name, domain, count in ((".uv_select_vert", "CORNER", "loops"), (".uv_select_edge", "CORNER", "loops"),
                                    (".uv_select_face", "FACE", "polygons")):
            auxiliary[name] = (domain, "BOOLEAN", "BoolAttribute", "BoolAttributeValue", counts[count])
    allowed.update(uv)
    allowed.update(auxiliary)
    reader.check()
    attributes = _bounded(mesh.attributes, 64)
    observed, headers, physical = {}, [], []
    for attribute in attributes:
        _kind(reader, attribute, frozenset({"FloatVectorAttribute", "Int2Attribute", "IntAttribute", "Float2Attribute", "BoolAttribute"}))
        name = _text(attribute.name)
        if name in observed or name not in allowed:
            raise refused("UNKNOWN_OR_DUPLICATE_MESH_ATTRIBUTE")
        domain, data_type, kind, _leaf, _count = allowed[name]
        props = reader.catalog(attribute, kind)
        actual = attribute.domain, attribute.data_type
        if actual != (domain, data_type):
            raise refused("MESH_ATTRIBUTE_SCHEMA")
        # Metadata admission describes physical storage without reading it.
        # The normal graph gate separately refuses all 5.2 SINGLE rows before
        # geometry/data acquisition; typed preparation remains a later stage.
        storage_present = any(prop.identifier == "storage_type" for prop in props)
        storage = "LEGACY_ARRAY"
        if reader.build == b"d13f752e3b9c":
            if not storage_present:
                raise refused("ATTRIBUTE_SINGLE_OR_UNKNOWN_STORAGE")
            storage = attribute.storage_type
            if type(storage) is not str or storage not in {"ARRAY", "SINGLE"} or (storage == "SINGLE" and data_type not in {"BOOLEAN", "FLOAT2"}):
                raise refused("ATTRIBUTE_SINGLE_OR_UNKNOWN_STORAGE")
        elif storage_present:
            raise refused("ATTRIBUTE_STORAGE_SCHEMA_CHANGED")
        headers.append((name, *actual))
        physical.append((name, *actual, storage, _count))
        observed[name] = attribute
    if any(name not in observed for name in uv) or any(layout[4] and name not in observed for name, layout in required.items()):
        raise refused("PHYSICAL_GEOMETRY_OR_UV_STORAGE_MISSING")
    # Auxiliary UV flags are optional physical buffers. The layer boolean
    # collection getters can create missing buffers, so never query them. Keep
    # absence separate from an existing all-false buffer in the hashed graph.
    present_uv = {name: (observed[name], allowed[name]) for name in (*uv, *auxiliary) if name in observed}
    auxiliary_inventory = tuple((name, name in observed) for name in sorted(auxiliary))
    # These immutable headers survive native CustomData layer-array changes.
    # Returned wrappers are borrowed views for immediate use only.
    return tuple(headers), present_uv, auxiliary_inventory, tuple(physical)

def _legacy_keys(owner: Any, allowed: set[str]) -> tuple[str, ...]:
    names = tuple(_text(name, 128) for name in _bounded(owner.keys(), 128))
    if len(set(names)) != len(names) or not set(names) <= allowed:
        raise refused("UNQUALIFIED_CUSTOM_PROPERTIES")
    return tuple(sorted(names))


def _keys(reader: _Reader | Any, owner: Any, kind: str | None = None,
          allowed: set[str] | None = None) -> tuple[str, ...]:
    if kind is None:
        if allowed is not None:
            raise refused("CUSTOM_PROPERTY_POLICY_UNQUALIFIED")
        return _legacy_keys(reader, owner)
    if allowed is None:
        raise refused("CUSTOM_PROPERTY_POLICY_UNQUALIFIED")
    reader.catalog(owner, kind)
    # Exact pinned SDNA declarations have no USER-IDProperty callback. In 5.2
    # NodeSocket.prop is SYSTEM storage instead; stock keys() rejects it. This
    # is a user-property API policy, not an observation of hidden SYSTEM data.
    no_user = kind in {"TexMapping", "ColorMapping", "ColorRamp", "ColorRampElement"}
    no_user |= reader.build == b"d13f752e3b9c" and kind in SOCKETS
    if no_user:
        if allowed:
            raise refused("USER_CUSTOM_PROPERTIES_UNSUPPORTED")
        return ()
    if kind not in {"Image", "Material", "ShaderNodeTree", "Mesh", "Object", *NODES, *SOCKETS}:
        raise refused("CUSTOM_PROPERTY_POLICY_UNQUALIFIED")
    method = _keys_method(reader.bpy, type(owner))
    reader.check()
    names = tuple(_text(name, 128) for name in _bounded(method(owner), 128))
    reader.check()
    if len(set(names)) != len(names) or not set(names) <= allowed:
        raise refused("UNQUALIFIED_CUSTOM_PROPERTIES")
    return tuple(sorted(names))


def _primitive_fields(reader: _Reader, owner: Any, kind: str,
                      *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    """All admitted native writable primitives, under a pinned complete catalog."""
    result = {}
    for prop in reader.catalog(owner, kind):
        if prop.is_readonly or prop.is_runtime or prop.identifier in exclude:
            continue
        if prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue  # Relationships/collections have explicit finite readers below.
        reader.check()
        raw = getattr(owner, prop.identifier)
        if prop.type == "ENUM" and prop.is_enum_flag:
            if type(raw) is not set or len(raw) > 128:
                raise refused("ENUM_FLAG_SHAPE")
            value = sorted(_text(item, 128) for item in raw)
        elif prop.type in {"STRING", "ENUM"}:
            value = _text(raw, 4096 if prop.type == "STRING" else 128, blank=True)
        elif prop.array_length:
            values = _bounded(raw, prop.array_length)
            if len(values) != prop.array_length:
                raise refused("PRIMITIVE_ARRAY_SHAPE")
            value = [_float(item) if prop.type == "FLOAT" else _bool(item) if prop.type == "BOOLEAN"
                     else _int(item, 2**53 - 1, minimum=-(2**53 - 1)) for item in values]
        else:
            value = _float(raw) if prop.type == "FLOAT" else _bool(raw) if prop.type == "BOOLEAN" else _int(raw, 2**53 - 1, minimum=-(2**53 - 1))
        result[prop.identifier] = value
    return result


def _ref(reader: _Reader, owner: Any, kind: str) -> dict[str, str]:
    row = reader.local_id(owner, kind)
    return {"kind": row["kind"], "name": row["name"]}


def _kind(reader: _Reader, owner: Any, allowed: frozenset[str]) -> str:
    """Select an exact native class before resolving any unknown leaf getter."""
    for kind in sorted(allowed):
        if type(owner) is getattr(reader.bpy.types, kind, None):
            reader.catalog(owner, kind)
            return kind
    failure = refused("UNQUALIFIED_NATIVE_LEAF_CLASS")
    # The native type-name descriptor bypasses both instance and metaclass
    # getters. Diagnostics identify unsupported types without inspecting them.
    failure.context["native_type"] = _TYPE_NAME.__get__(type(owner), type(type(owner)))[:128]
    raise failure


class _Stream:
    """One bounded authored stream feeds portable/native and per-ID hashes."""
    def __init__(self):
        self.bytes = 0
        self.native, self.portable = hashlib.sha256(), hashlib.sha256()
        self.consumer_native, self.consumer_portable = hashlib.sha256(), hashlib.sha256()
        self.content: Any = None
        self.consumer = False
        self.rows: list[dict[str, Any]] = []

    def _add(self, raw: bytes, *, native_only: bool = False) -> None:
        self.bytes += len(raw)
        if self.bytes > MAX_CANONICAL_BYTES:
            raise refused("CANONICAL_GRAPH_STREAM_BUDGET")
        self.native.update(raw)
        if not native_only:
            self.portable.update(raw)
            if self.content is not None:
                self.content.update(raw)
        if self.consumer:
            self.consumer_native.update(raw)
            if not native_only:
                self.consumer_portable.update(raw)

    def emit(self, name: str, value: Any) -> None:
        self._add(_canonical([name, value]) + b"\n")

    def native_token(self, label: str, value: int) -> None:
        self._add(_canonical(["native", label, _int(value, 2**64 - 1, minimum=1)]) + b"\n", native_only=True)

    def begin(self, row: dict[str, Any], *, consumer: bool) -> None:
        if len(self.rows) >= 16 or self.content is not None:
            raise refused("GRAPH_ID_ROW_BUDGET_OR_NESTING")
        self.consumer, self.content = consumer, hashlib.sha256()
        self.emit("ID", {"kind": row["kind"], "name": row["name"]})
        self._add(_canonical(["native_ID", row["pointer"], row["session_uid"]]) + b"\n", native_only=True)

    def end(self, row: dict[str, Any]) -> None:
        self.rows.append({**row, "content_sha256": self.content.hexdigest()})
        self.content, self.consumer = None, False


def _image_metadata(reader: _Reader, image: Any, *, helper: bool, original: Any,
                    expected_record: str | None) -> dict[str, Any]:
    from .tools import image_portability as storage

    identity = reader.local_id(image, "Image")
    reader.no_animation(image, "Image")
    if image.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")  # Before size, is_float and pixels.
    reader.check()
    width, height = tuple(image.size)
    if (type(width) is not int or type(height) is not int or not 1 <= width <= 4096
            or not 1 <= height <= 4096 or width * height > 16_777_216):
        raise refused("IMAGE_DIMENSIONS")
    reader.catalog(image.colorspace_settings, "ColorManagedInputColorspaceSettings")
    if (image.source != "FILE" or image.file_format != "OPEN_EXR" or image.is_float is not True
            or image.channels != 4 or image.colorspace_settings.name != "Non-Color"
            or image.alpha_mode != "CHANNEL_PACKED" or image.is_multiview is not False):
        raise refused("IMAGE_STORAGE_OR_ROLES")
    names = _keys(image, {storage.METADATA_KEY, storage.OWNER_KEY, LIFECYCLE_KEY} if helper else set())
    record = None
    snapshot_metadata = None
    if helper:
        if storage.METADATA_KEY not in names or storage.OWNER_KEY not in names or image.get(storage.OWNER_KEY) is not original:
            raise refused("SNAPSHOT_NATIVE_OWNER_OR_METADATA")
        if LIFECYCLE_KEY in names:
            record = validate_lifecycle_record(image[LIFECYCLE_KEY])
        if record != expected_record:
            raise refused("LIFECYCLE_RECORD_CHANGED")
        snapshot_metadata = _text(image[storage.METADATA_KEY], 4096)
        if image.use_fake_user is not True or image.users != 1:
            raise refused("SNAPSHOT_RETENTION_OR_INCOMING_USERS")
    fields = {"source": image.source, "file_format": image.file_format,
              "filepath": _text(image.filepath, 4096, blank=True),
              "filepath_raw": _text(image.filepath_raw, 4096, blank=True),
              "width": width, "height": height, "channels": 4, "is_float": True,
              "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED", "is_multiview": False,
              "use_fake_user": _bool(image.use_fake_user), "users": _int(image.users, 64),
              "snapshot_metadata": snapshot_metadata,
              "native_owner": _ref(reader, original, "Image") if helper else None}
    return {"identity": identity, "static": fields,
            "volatile": {"has_data": True, "is_dirty": _bool(image.is_dirty), "lifecycle_record": record}}


def _user_map(reader: _Reader, owners: tuple[Any, ...]) -> dict[Any, tuple[Any, ...]]:
    reader.check()
    before = _query_context(reader)
    supplied = reader.bpy.data.user_map(subset=set(owners))
    reader.check()
    if _query_context(reader) != before:
        raise refused("NATIVE_REFERENCE_QUERY_CONTEXT_CHANGED")
    if type(supplied) is not dict or set(supplied) != set(owners) or any(type(value) is not set for value in supplied.values()):
        raise refused("NATIVE_REVERSE_MAP_SHAPE")
    result = {}
    for owner in owners:
        result[owner] = _bounded(supplied.get(owner, ()), 16)
    return result


def _collection_closure(reader: _Reader, obj: Any, incoming: tuple[Any, ...], *, checkpoint_roles: Any = None) -> tuple[Any, ...]:
    """Source-attributed embedded master/direct children; no learned counts."""
    bpy = reader.bpy
    scene = bpy.context.scene
    reader.local_id(scene, "Scene")
    reader.no_animation(scene, "Scene")
    root = scene.collection
    reader.local_id(root, "Collection")
    if root.is_embedded_data is not True:
        raise refused("EMBEDDED_SCENE_MASTER_REQUIRED")
    if _user_map(reader, (root,))[root]:
        # user_map deliberately skips the embedded owner and root LayerCollection
        # slots. Any returned owner is an additional, unowned reference.
        raise refused("EMBEDDED_MASTER_EXTERNAL_CONSUMER")
    collections = []
    scenes = []
    for owner in incoming:
        if type(owner) is bpy.types.Scene:
            if owner is not scene:
                raise refused("FOREIGN_SCENE_CONSUMER")
            scenes.append(owner)
        elif type(owner) is bpy.types.Collection:
            reader.local_id(owner, "Collection")
            reader.no_animation(owner, "Collection")
            if (owner is root or owner.is_embedded_data is not False
                    or root.children.get(owner.name) is not owner or len(owner.children)
                    or owner.objects.get(obj.name) is not obj):
                raise refused("NESTED_OR_REBOUND_COLLECTION_CONSUMER")
            collections.append(owner)
        else:
            raise refused("UNKNOWN_OBJECT_CONSUMER")
    root_link = root.objects.get(obj.name) is obj
    if root_link:
        collections.append(root)
    if not collections:
        raise refused("OWNING_COLLECTION_MISSING")
    paths, memberships = _scene_paths(reader, scene, root, obj)
    _user_count(reader, scene, root, expected=1 + paths.get(root, 0), reason="SCENE_MASTER_REFERENCE_ROLES_CHANGED")
    expected_object_count = int(root_link) + memberships
    if bool(scenes) is not bool(expected_object_count):
        raise refused("SCENE_OBJECT_REFERENCE_ROLES_CHANGED")
    if checkpoint_roles is None:
        _user_count(reader, scene, obj, expected=expected_object_count, reason="SCENE_OBJECT_REFERENCE_ROLES_CHANGED")
    else:
        # Private B2 admission supplies a retained, source-sealed role proof,
        # never a caller-selected count or a wildcard for extra consumers.
        checkpoint_roles.check_scene_object_count(reader, scene, obj, expected_object_count)
    closure: set[Any] = {scene}
    for collection in (*collections, root):
        reader.check()
        if collection is root:
            closure.add(root)
            if root_link:
                _user_count(reader, root, obj, expected=1, reason="MASTER_OBJECT_REFERENCE_ROLES_CHANGED")
            continue
        parents = _user_map(reader, (collection,))[collection]
        if parents != (scene,):
            raise refused("UNOWNED_COLLECTION_CONSUMER")
        _user_count(reader, root, collection, expected=1, reason="DIRECT_CHILD_REFERENCE_ROLES_CHANGED")
        _user_count(reader, scene, collection, expected=1 + paths.get(collection, 0), reason="DIRECT_CHILD_REFERENCE_ROLES_CHANGED")
        _user_count(reader, collection, obj, expected=1, reason="DIRECT_CHILD_REFERENCE_ROLES_CHANGED")
        closure.add(collection)
    if any(owner is not scene for owner in scenes):
        raise refused("FOREIGN_SCENE_CONSUMER")
    if not any(collection is root or root.children.get(collection.name) is collection for collection in collections):
        raise refused("OBJECT_NOT_IN_CURRENT_SCENE")
    return tuple(sorted(closure, key=lambda owner: (owner.bl_rna.identifier, owner.name)))


def _consumers(reader: _Reader, original: Any, helper: Any, materials: tuple[Any, ...]
               ) -> tuple[tuple[Any, ...], dict[Any, tuple[Any, ...]]]:
    bpy = reader.bpy
    trees = tuple(material.node_tree for material in materials)
    if len({id(tree) for tree in trees}) != len(trees):
        raise refused("SHARED_MATERIAL_TREE")
    users = _user_map(reader, (original, helper, *materials, *trees))
    if users[helper] or any(owner not in {helper, *materials, *trees} for owner in users[original]):
        raise refused("UNKNOWN_IMAGE_CONSUMER")
    objects: set[Any] = set()
    for material, tree in zip(materials, trees, strict=True):
        reader.local_id(material, "Material")
        reader.local_id(tree, "ShaderNodeTree")
        reader.no_animation(material, "Material")
        reader.no_animation(tree, "ShaderNodeTree")
        if material.use_nodes is not True or tree.is_embedded_data is not True or tree.users != 1:
            raise refused("UNSHARED_EMBEDDED_TREE_REQUIRED")
        if any(owner is not material for owner in users[tree]):
            raise refused("UNKNOWN_TREE_CONSUMER")
        for owner in users[material]:
            if type(owner) is bpy.types.Object:
                objects.add(owner)
            elif type(owner) is bpy.types.Mesh:
                mesh_users = _user_map(reader, (owner,))[owner]
                if len(mesh_users) != 1 or type(mesh_users[0]) is not bpy.types.Object:
                    raise refused("SHARED_OR_UNKNOWN_MESH_CONSUMER")
                objects.add(mesh_users[0])
            else:
                raise refused("UNKNOWN_MATERIAL_CONSUMER")
    if len(objects) > 2:
        raise refused("OBJECT_CONSUMER_BUDGET")
    ordered = tuple(sorted(objects, key=lambda obj: _text(obj.name)))
    seen_meshes: set[Any] = set()
    for obj in ordered:
        reader.local_id(obj, "Object")
        reader.no_animation(obj, "Object")
        if (obj.type != "MESH" or obj.mode != "OBJECT" or obj.parent is not None
                or len(obj.children) or len(obj.modifiers) or len(obj.constraints)
                or len(obj.vertex_groups) or obj.instance_type != "NONE"):
            raise refused("OBJECT_HIERARCHY_MODIFIER_RIG_OR_INSTANCE")
        mesh = obj.data
        reader.local_id(mesh, "Mesh")
        reader.no_animation(mesh, "Mesh")
        if mesh in seen_meshes or mesh.users != 1 or mesh.shape_keys is not None or mesh.is_editmode:
            raise refused("SHARED_SHAPEKEY_OR_EDIT_MESH")
        seen_meshes.add(mesh)
        map_rows = _user_map(reader, (obj, mesh))
        if map_rows[mesh] != (obj,):
            raise refused("UNKNOWN_MESH_CONSUMER")
        closure = _collection_closure(reader, obj, map_rows[obj])
        map_rows[obj] = tuple(dict.fromkeys((*map_rows[obj], *closure)))
        users.update(map_rows)
    return ordered, users


def _socket(reader: _Reader, stream: _Stream, socket: Any, node: Any, tree: Any = None,
            retained: list[Any] | None = None) -> dict[str, Any]:
    kind = _kind(reader, socket, SOCKETS)
    if socket.bl_idname != kind:
        raise refused("SOCKET_CLASS_UNQUALIFIED")
    props = reader.catalog(socket, kind)
    if tree is None and retained is None:
        if socket.node is not node:
            raise refused("SOCKET_OWNER_CHANGED")
    else:
        if tree is None or type(retained) is not list:
            raise refused("SOCKET_IDENTITY_ARGUMENT_SHAPE")
        _socket_identity(reader, socket, tree, retained)
        _unshadowed(type(socket), ("node",))
        if _node_identity(reader, socket.node, tree, retained) != _node_identity(reader, node, tree, retained):
            raise refused("SOCKET_OWNER_CHANGED")
    stream.native_token("socket", socket.as_pointer())
    names = {prop.identifier for prop in props}
    if kind == "NodeSocketShader":
        if "default_value" in names:
            raise refused("SHADER_SOCKET_DEFAULT_SCHEMA_CHANGED")
        default = None
    else:
        descriptor = next((prop for prop in props if prop.identifier == "default_value"), None)
        if descriptor is None or descriptor.is_runtime:
            raise refused("SOCKET_DEFAULT_SCHEMA_CHANGED")
        value = socket.default_value
        if kind == "NodeSocketColor":
            default = _vector(value, 4)
        elif kind == "NodeSocketVector":
            default = _vector(value, 3)
        elif kind == "NodeSocketBool":
            default = _bool(value)
        elif kind == "NodeSocketInt":
            default = _int(value, 2**31 - 1, minimum=-(2**31))
        else:
            default = _float(value)
    if tree is None:
        _keys(socket, set())
    else:
        _keys(reader, socket, kind, set())
    return {"name": _text(socket.name, 128, blank=True), "identifier": _text(socket.identifier, 128),
            "class": kind, "default": default, "is_linked": _bool(socket.is_linked),
            "authored": _primitive_fields(reader, socket, kind, exclude=frozenset({"default_value"}))}


def _relationships(reader: _Reader, owner: Any, kind: str, *, pointers: frozenset[str],
                    collections: frozenset[str]) -> None:
    for prop in reader.catalog(owner, kind):
        if prop.type == "POINTER" and prop.identifier != "rna_type" and prop.identifier not in pointers:
            raise refused("UNPROJECTED_POINTER:" + kind + "." + prop.identifier)
        if prop.type == "COLLECTION" and prop.identifier not in collections:
            raise refused("UNPROJECTED_COLLECTION:" + kind + "." + prop.identifier)


def _mapping(reader: _Reader, stream: _Stream, node: Any, tree: Any,
             retained: list[Any] | None = None) -> dict[str, Any]:
    """Complete bounded embedded SDNA mapping/ramp fields; never setters/path APIs."""
    result = {}
    for field, kind in (("texture_mapping", "TexMapping"), ("color_mapping", "ColorMapping")):
        descriptor = next((prop for prop in reader.catalog(node, "ShaderNodeTexImage") if prop.identifier == field), None)
        if descriptor is None or descriptor.type != "POINTER" or descriptor.is_runtime or descriptor.fixed_type.identifier != kind:
            raise refused("MAPPING_POINTER_SCHEMA_UNQUALIFIED")
        reader.check()
        owner = getattr(node, field)
        reader.catalog(owner, kind)
        if retained is None:
            if owner.id_data is not tree:
                raise refused("MAPPING_NATIVE_OWNER_CHANGED")
        else:
            _rna_identity(reader, owner, kind, tree, retained)
            _keys(reader, owner, kind, set())
        _relationships(reader, owner, kind, pointers=frozenset({"color_ramp"}) if kind == "ColorMapping" else frozenset(),
                         collections=frozenset())
        stream.native_token(field, owner.as_pointer())
        result[field] = _primitive_fields(reader, owner, kind)
        if kind == "ColorMapping":
            reader.check()
            ramp = owner.color_ramp
            reader.catalog(ramp, "ColorRamp")
            reader.class_catalog("ColorRampElements")
            if retained is None:
                if ramp.id_data is not tree:
                    raise refused("RAMP_NATIVE_OWNER_CHANGED")
            else:
                _rna_identity(reader, ramp, "ColorRamp", tree, retained)
                _keys(reader, ramp, "ColorRamp", set())
            _relationships(reader, ramp, "ColorRamp", pointers=frozenset(), collections=frozenset({"elements"}))
            stream.native_token("color_ramp", ramp.as_pointer())
            elements = _bounded(ramp.elements, 32)
            if not elements:
                raise refused("COLOR_RAMP_ELEMENT_SHAPE")
            rows = []
            for element in elements:
                reader.catalog(element, "ColorRampElement")
                if retained is None:
                    if element.id_data is not tree:
                        raise refused("RAMP_ELEMENT_NATIVE_OWNER_CHANGED")
                else:
                    _rna_identity(reader, element, "ColorRampElement", tree, retained)
                    _keys(reader, element, "ColorRampElement", set())
                _relationships(reader, element, "ColorRampElement", pointers=frozenset(), collections=frozenset())
                stream.native_token("ramp_element", element.as_pointer())
                fields = _primitive_fields(reader, element, "ColorRampElement")
                # Native alpha is an alias of color[3], not separate evidence.
                color = _vector(element.color, 4)
                alpha = _float(element.alpha)
                if color[3] != alpha:
                    raise refused("RAMP_ALPHA_ALIAS_CHANGED")
                fields.update(color=color, alpha=alpha, position=_float(element.position))
                rows.append(fields)
            result[field]["color_ramp"] = {"authored": _primitive_fields(reader, ramp, "ColorRamp"), "elements": rows}
    return result


def _material(reader: _Reader, stream: _Stream, material: Any, original: Any,
              totals: dict[str, int]) -> None:
    row = reader.local_id(material, "Material")
    _runtime_absent(reader, material, "Material")
    _keys(material, set())
    stream.begin(row, consumer=True)
    stream.emit("material", _primitive_fields(reader, material, "Material"))
    stream.end(row)
    tree = material.node_tree
    row = reader.local_id(tree, "ShaderNodeTree")
    _keys(tree, set())
    _runtime_absent(reader, tree, "ShaderNodeTree")
    stream.begin(row, consumer=True)
    stream.emit("tree", _primitive_fields(reader, tree, "ShaderNodeTree"))
    nodes = _bounded(tree.nodes, MAX_NODES)
    links = _bounded(tree.links, MAX_LINKS)
    for node in nodes:
        _kind(reader, node, NODES)
    totals["nodes"] += len(nodes)
    totals["links"] += len(links)
    if totals["nodes"] > MAX_NODES or totals["links"] > MAX_LINKS:
        raise refused("NODE_OR_LINK_BUDGET")
    if len({_text(node.name) for node in nodes}) != len(nodes):
        raise refused("AMBIGUOUS_NODE_NAMES")
    socket_owners: dict[Any, tuple[str, str, str]] = {}
    source_bindings = 0
    for node in sorted(nodes, key=lambda item: item.name):
        reader.check()
        kind = _kind(reader, node, NODES)
        if node.bl_idname != kind:
            raise refused("NODE_CLASS_OR_NESTED_GROUP_UNQUALIFIED")
        reader.catalog(node, kind)
        _relationships(reader, node, kind,
                       pointers=frozenset({"parent", "image", "image_user", "texture_mapping", "color_mapping"}) if kind == "ShaderNodeTexImage" else frozenset({"parent"}),
                       collections=frozenset({"inputs", "outputs", "internal_links", "panel_states"}))
        if node.id_data is not tree or node.parent is not None:
            raise refused("NODE_OWNER_OR_PARENT_UNQUALIFIED")
        _keys(node, set())
        stream.native_token("node", node.as_pointer())
        value = {"name": node.name, "class": kind, "authored": _primitive_fields(reader, node, kind)}
        if any(prop.identifier == "panel_states" for prop in reader.catalog(node, kind)) and len(node.panel_states):
            raise refused("NONEMPTY_NODE_PANEL_STATE_UNQUALIFIED")
        for direction in ("inputs", "outputs"):
            sockets = _bounded(getattr(node, direction), MAX_SOCKETS)
            totals["sockets"] += len(sockets)
            if totals["sockets"] > MAX_SOCKETS:
                raise refused("SOCKET_BUDGET")
            identifiers = [_text(socket.identifier, 128) for socket in sockets]
            if len(set(identifiers)) != len(identifiers):
                raise refused("AMBIGUOUS_SOCKET_IDENTIFIERS")
            value[direction] = [_socket(reader, stream, socket, node) for socket in sockets]
            socket_owners.update({socket: (node.name, direction, socket.identifier) for socket in sockets})
        if kind == "ShaderNodeTexImage":
            if node.image is not None and node.image is not original:
                raise refused("UNDECLARED_IMAGE_BINDING")
            value["image"] = None if node.image is None else _ref(reader, original, "Image")
            source_bindings += node.image is original
            reader.catalog(node.image_user, "ImageUser")
            if node.image_user.use_auto_refresh:
                raise refused("AUTOMATIC_IMAGE_REFRESH_UNQUALIFIED")
            value["image_user"] = _primitive_fields(reader, node.image_user, "ImageUser")
            value["mapping"] = _mapping(reader, stream, node, tree)
        if any(prop.identifier == "internal_links" for prop in reader.catalog(node, kind)):
            internal = []
            for link in _bounded(node.internal_links, MAX_SOCKETS):
                reader.catalog(link, "NodeLink")
                if link.from_socket not in socket_owners or link.to_socket not in socket_owners:
                    raise refused("INTERNAL_LINK_OWNER_UNQUALIFIED")
                source, target = socket_owners[link.from_socket], socket_owners[link.to_socket]
                if source[:2] != (node.name, "inputs") or target[:2] != (node.name, "outputs"):
                    raise refused("INTERNAL_LINK_DIRECTION_UNQUALIFIED")
                internal.append([source, target])
            value["internal_links"] = internal
        stream.emit("node", value)
    if source_bindings == 0:
        raise refused("DECLARED_MATERIAL_HAS_NO_SOURCE_BINDING")
    for link in links:
        reader.catalog(link, "NodeLink")
        if (link.from_node not in nodes or link.to_node not in nodes
                or link.from_socket not in socket_owners or link.to_socket not in socket_owners):
            raise refused("LINK_OWNER_UNQUALIFIED")
        source, target = socket_owners[link.from_socket], socket_owners[link.to_socket]
        if source[1] != "outputs" or target[1] != "inputs":
            raise refused("LINK_DIRECTION_UNQUALIFIED")
        stream.emit("link", {"from": source, "to": target, "valid": _bool(link.is_valid), "muted": _bool(link.is_muted)})
    stream.end(row)


def _array_attribute_inventory(reader: _Reader, mesh: Any, counts: dict[str, int],
                          uv_names: tuple[str, ...]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    required = {"position": ("POINT", "FLOAT_VECTOR", "FloatVectorAttribute", "FloatVectorAttributeValue", counts["vertices"]),
                ".edge_verts": ("EDGE", "INT32_2D", "Int2Attribute", "Int2AttributeValue", counts["edges"]),
                ".corner_vert": ("CORNER", "INT", "IntAttribute", "IntAttributeValue", counts["loops"]),
                ".corner_edge": ("CORNER", "INT", "IntAttribute", "IntAttributeValue", counts["loops"])}
    allowed = dict(required)
    allowed["material_index"] = ("FACE", "INT", "IntAttribute", "IntAttributeValue", counts["polygons"])
    for name, domain, count in ((".select_vert", "POINT", "vertices"), (".hide_vert", "POINT", "vertices"),
                                (".select_edge", "EDGE", "edges"), (".hide_edge", "EDGE", "edges"),
                                ("uv_seam", "EDGE", "edges"), ("sharp_edge", "EDGE", "edges"),
                                (".select_poly", "FACE", "polygons"), (".hide_poly", "FACE", "polygons"),
                                ("sharp_face", "FACE", "polygons")):
        allowed[name] = (domain, "BOOLEAN", "BoolAttribute", "BoolAttributeValue", counts[count])
    uv = {}
    for name in uv_names:
        uv[name] = ("CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue", counts["loops"])
        for prefix in ((".pn.", ".vs.", ".es.") if reader.build == b"62c1db4208e8" else (".pn.",)):
            uv[prefix + name] = ("CORNER", "BOOLEAN", "BoolAttribute", "BoolAttributeValue", counts["loops"])
    if uv_names and reader.build == b"d13f752e3b9c":
        for name, domain, count in ((".uv_select_vert", "CORNER", "loops"), (".uv_select_edge", "CORNER", "loops"),
                                    (".uv_select_face", "FACE", "polygons")):
            uv[name] = (domain, "BOOLEAN", "BoolAttribute", "BoolAttributeValue", counts[count])
    allowed.update(uv)
    attributes = _bounded(mesh.attributes, 64)
    observed = {}
    for attribute in attributes:
        _kind(reader, attribute, frozenset({"FloatVectorAttribute", "Int2Attribute", "IntAttribute", "Float2Attribute", "BoolAttribute"}))
        name = _text(attribute.name)
        if name in observed or name not in allowed:
            raise refused("UNKNOWN_OR_DUPLICATE_MESH_ATTRIBUTE")
        domain, data_type, kind, _leaf, _count = allowed[name]
        props = reader.catalog(attribute, kind)
        if (attribute.domain, attribute.data_type) != (domain, data_type):
            raise refused("MESH_ATTRIBUTE_SCHEMA")
        # In 5.2 a data getter materializes SINGLE storage, so inspect metadata
        # and ARRAY first. 4.5 COW may occur, but no optional layer is created.
        storage_present = any(prop.identifier == "storage_type" for prop in props)
        if reader.build == b"d13f752e3b9c":
            if not storage_present or attribute.storage_type != "ARRAY":
                raise refused("ATTRIBUTE_SINGLE_OR_UNKNOWN_STORAGE")
        elif storage_present:
            raise refused("ATTRIBUTE_STORAGE_SCHEMA_CHANGED")
        observed[name] = attribute
    if any(name not in observed for name in uv) or any(layout[4] and name not in observed for name, layout in required.items()):
        raise refused("PHYSICAL_GEOMETRY_OR_UV_STORAGE_MISSING")
    return attributes, {name: (observed[name], allowed[name]) for name in uv}


def _mesh(reader: _Reader, stream: _Stream, mesh: Any, materials: tuple[Any, ...],
           totals: dict[str, int]) -> None:
    from .uv_edit_guard import _manual_texspace_vector, _mesh_properties

    row = reader.local_id(mesh, "Mesh")
    _runtime_absent(reader, mesh, "Mesh")
    _props, policy = _mesh_properties(reader.bpy, mesh)
    # Raw cycles presence is already reviewed above. Other custom data is
    # outside this profile; an empty raw group is the only admitted exception.
    custom = _keys(mesh, {"cycles"})
    if custom:
        from .tools import _scene_mutation as scene
        values = scene.custom(mesh)
        if values != (("cycles", ()),) and values != (("cycles", ("group", ())),):
            raise refused("NONEMPTY_MESH_RUNTIME_OR_CUSTOM_STORAGE")
    counts = {name: len(getattr(mesh, name)) for name in ("vertices", "edges", "polygons", "loops")}
    for name, maximum in (("vertices", MAX_VERTICES), ("edges", MAX_EDGES), ("polygons", MAX_POLYGONS), ("loops", MAX_LOOPS)):
        totals[name] += counts[name]
        if totals[name] > maximum:
            raise refused("AGGREGATE_GEOMETRY_BUDGET")
    layers = _bounded(mesh.uv_layers, MAX_UV_MAPS)
    for layer in layers:
        reader.catalog(layer, "MeshUVLoopLayer")
    uv_names = tuple(_text(layer.name) for layer in layers)
    if len(set(uv_names)) != len(uv_names) or mesh.has_custom_normals or len(mesh.color_attributes):
        raise refused("CUSTOM_NORMAL_COLOR_OR_AMBIGUOUS_UV")
    attributes, uv = _array_attribute_inventory(reader, mesh, counts, uv_names)
    stream.begin(row, consumer=True)
    fields = _primitive_fields(reader, mesh, "Mesh", exclude=frozenset({"texspace_location", "texspace_size"}))
    auto = policy[-4][0]
    if auto is False:
        fields.update({name: [_float(value) for value in _manual_texspace_vector(mesh, name)]
                       for name in ("texspace_location", "texspace_size")})
    stream.emit("mesh", {"fields": fields, "counts": counts, "manual_texspace_vectors_read": not auto,
                         "material_bindings": [_ref(reader, material, "Material") for material in mesh.materials]})
    for index, vertex in enumerate(mesh.vertices):
        reader.check()
        reader.catalog(vertex, "MeshVertex")
        if vertex.index != index or len(vertex.groups):
            raise refused("VERTEX_INDEX_OR_WEIGHT_MEMBERSHIPS")
        stream.emit("vertex", [index, _vector(vertex.co, 3), _bool(vertex.select), _bool(vertex.hide)])
    for index, edge in enumerate(mesh.edges):
        reader.check()
        reader.catalog(edge, "MeshEdge")
        endpoints = tuple(edge.vertices)
        if edge.index != index or len(endpoints) != 2:
            raise refused("EDGE_INDEX_OR_SHAPE")
        stream.emit("edge", [index, [_int(value, counts["vertices"] - 1) for value in endpoints],
                             _bool(edge.use_seam), _bool(edge.use_edge_sharp), _bool(edge.select), _bool(edge.hide)])
    next_loop = 0
    for index, face in enumerate(mesh.polygons):
        reader.check()
        reader.catalog(face, "MeshPolygon")
        loop_total = _int(face.loop_total, counts["loops"], minimum=3)
        vertices = _bounded(face.vertices, loop_total)
        if face.index != index or face.loop_start != next_loop or loop_total != len(vertices):
            raise refused("POLYGON_LOOP_TOPOLOGY")
        next_loop += len(vertices)
        if next_loop > counts["loops"]:
            raise refused("POLYGON_LOOP_BUDGET")
        stream.emit("polygon", [index, [_int(value, counts["vertices"] - 1) for value in vertices], face.loop_start,
                                face.loop_total, _int(face.material_index, max(0, len(mesh.materials) - 1)),
                                _bool(face.use_smooth), _bool(face.select), _bool(face.hide)])
    if next_loop != counts["loops"]:
        raise refused("INCOMPLETE_LOOP_COVERAGE")
    for index, loop in enumerate(mesh.loops):
        reader.check()
        reader.catalog(loop, "MeshLoop")
        if loop.index != index:
            raise refused("LOOP_INDEX")
        stream.emit("loop", [index, _int(loop.vertex_index, counts["vertices"] - 1), _int(loop.edge_index, counts["edges"] - 1)])
    stream.emit("attribute_inventory", [[attribute.name, attribute.domain, attribute.data_type] for attribute in attributes])
    for name in sorted(uv):
        attribute, (_domain, kind, _class, leaf, count) = uv[name]
        reader.check()
        data = attribute.data  # Only after complete physical/storage preflight.
        if len(data) != count:
            raise refused("UV_ATTRIBUTE_LENGTH")
        for index, item in enumerate(data):
            reader.check()
            reader.catalog(item, leaf)
            value = _vector(item.vector, 2) if kind == "FLOAT2" else _bool(item.value)
            stream.emit("uv_attribute", [name, index, value])
    if layers:
        reader.class_catalog("UVLoopLayers")
        active_index = _int(mesh.uv_layers.active_index, len(layers) - 1)
    else:
        reader.class_catalog("UVLoopLayers")
        active_index = _int(mesh.uv_layers.active_index, 0, minimum=-1)
    roles = [[layer.name, _bool(layer.active_render), _bool(layer.active_clone)] for layer in layers]
    if layers and (sum(role[1] for role in roles) != 1 or sum(role[2] for role in roles) != 1):
        raise refused("UV_ACTIVE_RENDER_OR_CLONE_ROLE_UNAVAILABLE")
    stream.emit("uv_roles", {"order": uv_names, "active_index": active_index, "roles": roles})
    stream.end(row)


def _object(reader: _Reader, stream: _Stream, obj: Any, materials: tuple[Any, ...],
             users: tuple[Any, ...], totals: dict[str, int]) -> None:
    row = reader.local_id(obj, "Object")
    _runtime_absent(reader, obj, "Object")
    _keys(obj, set())
    slots = _bounded(obj.material_slots, MAX_SLOTS)
    totals["slots"] += len(slots)
    if totals["slots"] > MAX_SLOTS or len(obj.data.materials) != len(slots):
        raise refused("MATERIAL_SLOT_BUDGET_OR_ALIAS")
    bindings = []
    for index, slot in enumerate(slots):
        reader.catalog(slot, "MaterialSlot")
        if slot.link != "DATA" or slot.material not in materials or obj.data.materials[index] is not slot.material:
            raise refused("UNDECLARED_OR_OBJECT_LINKED_MATERIAL")
        bindings.append(_ref(reader, slot.material, "Material"))
    reader.check()
    parent_inverse = _bounded(obj.matrix_parent_inverse, 4)
    if len(parent_inverse) != 4:
        raise refused("OBJECT_PARENT_INVERSE_MATRIX_SHAPE")
    stream.begin(row, consumer=True)
    stream.emit("object", {"authored": _primitive_fields(reader, obj, "Object",
                           exclude=frozenset({"matrix_world", "matrix_local", "matrix_basis", "dimensions", "matrix_parent_inverse"})),
                           "matrix_parent_inverse": [_vector(line, 4) for line in parent_inverse],
                           "mesh": _ref(reader, obj.data, "Mesh"), "slots": bindings,
                           "incoming": sorted([[_text(owner.bl_rna.identifier, 128), _text(owner.name),
                                               _int(owner.user_of_id(obj), 16)] for owner in users])})
    for owner in sorted(users, key=lambda item: (item.bl_rna.identifier, item.name)):
        stream.native_token("object_consumer", owner.as_pointer())
        stream.native_token("object_consumer_uid", owner.session_uid)
    stream.end(row)


@dataclass(frozen=True, slots=True)
class _Structure:
    original: Any
    snapshot: Any
    materials: tuple[Any, ...]
    objects: tuple[Any, ...]
    native_graph_sha256: str
    portable_graph_sha256: str
    native_rows: tuple[dict[str, Any], ...]
    original_metadata: dict[str, Any]
    snapshot_metadata: dict[str, Any]
    workload: dict[str, int]
    catalog_facts: tuple[tuple[str, str], ...]
    canonical_bytes: int


def _preflight_workload(reader: _Reader, objects: tuple[Any, ...], materials: tuple[Any, ...]) -> dict[str, int]:
    totals = dict.fromkeys(("vertices", "edges", "polygons", "loops", "slots", "nodes", "links", "sockets"), 0)
    for obj in objects:
        reader.check()
        mesh = obj.data
        for name, maximum in (("vertices", MAX_VERTICES), ("edges", MAX_EDGES), ("polygons", MAX_POLYGONS), ("loops", MAX_LOOPS)):
            totals[name] += len(getattr(mesh, name))
            if totals[name] > maximum:
                raise refused("AGGREGATE_GEOMETRY_BUDGET")
        totals["slots"] += len(obj.material_slots)
        if totals["slots"] > MAX_SLOTS or len(mesh.uv_layers) > MAX_UV_MAPS:
            raise refused("AGGREGATE_SLOT_OR_UV_BUDGET")
    for material in materials:
        tree = material.node_tree
        totals["nodes"] += len(tree.nodes)
        totals["links"] += len(tree.links)
        if totals["nodes"] > MAX_NODES or totals["links"] > MAX_LINKS:
            raise refused("NODE_OR_LINK_BUDGET")
        for node in _bounded(tree.nodes, MAX_NODES):
            _kind(reader, node, NODES)
            totals["sockets"] += len(node.inputs) + len(node.outputs)
            if totals["sockets"] > MAX_SOCKETS:
                raise refused("SOCKET_BUDGET")
    return totals


def _structure(reader: _Reader, image_name: str | None, snapshot_name: str,
                material_names: tuple[str, ...], expected_record: str | None) -> _Structure:
    reader.begin_pass()
    original, helper, materials, _identity = _identity_scope(reader, image_name, snapshot_name, material_names)
    original_metadata = _image_metadata(reader, original, helper=False, original=original, expected_record=None)
    snapshot_metadata = _image_metadata(reader, helper, helper=True, original=original, expected_record=expected_record)
    if (original_metadata["static"]["width"], original_metadata["static"]["height"]) != (
            snapshot_metadata["static"]["width"], snapshot_metadata["static"]["height"]):
        raise refused("SNAPSHOT_DIMENSIONS_DIFFER")
    objects, users = _consumers(reader, original, helper, materials)
    stream = _Stream()
    totals = dict.fromkeys(("vertices", "edges", "polygons", "loops", "slots", "nodes", "links", "sockets"), 0)
    expected_totals = _preflight_workload(reader, objects, materials)
    for material in materials:
        _material(reader, stream, material, original, totals)
    for obj in objects:
        _object(reader, stream, obj, materials, users[obj], totals)
        _mesh(reader, stream, obj.data, materials, totals)
    for metadata in (original_metadata, snapshot_metadata):
        row = metadata["identity"]
        stream.begin(row, consumer=True)
        stream.emit("image_static", metadata["static"])
        stream.end(row)
    if totals != expected_totals:
        raise refused("WORKLOAD_CHANGED_DURING_CAPTURE")
    return _Structure(original, helper, materials, objects, stream.native.hexdigest(), stream.portable.hexdigest(),
                       tuple(stream.rows), original_metadata, snapshot_metadata, totals,
                       tuple(sorted(reader.catalogs.items())), stream.bytes)


@dataclass(frozen=True, slots=True)
class PayloadCapture:
    """Active preparation buffers only; never serialize or put these in a plan."""
    current_pixels: array
    original_packed: bytes
    snapshot_packed: bytes
    current_pixels_sha256_float32_le: str
    original_packed_sha256: str
    original_decoded_pixels_sha256: str
    snapshot_packed_sha256: str

    def facts(self) -> dict[str, Any]:
        return {"current_pixels_sha256_float32_le": self.current_pixels_sha256_float32_le,
                "original_packed_sha256": self.original_packed_sha256,
                "original_decoded_pixels_sha256": self.original_decoded_pixels_sha256,
                "snapshot_packed_sha256": self.snapshot_packed_sha256,
                "original_packed_bytes": len(self.original_packed), "snapshot_packed_bytes": len(self.snapshot_packed)}


@dataclass(frozen=True, slots=True)
class GraphCapture:
    original: Any
    snapshot: Any
    materials: tuple[Any, ...]
    objects: tuple[Any, ...]
    native_graph_sha256: str
    portable_graph_sha256: str
    full_native_prefix_sha256: str
    full_portable_prefix_sha256: str
    native_identity_rows: tuple[dict[str, Any], ...]
    original_metadata: dict[str, Any]
    snapshot_metadata: dict[str, Any]
    workload: dict[str, int]
    resource_facts: dict[str, Any]
    catalog_facts: tuple[tuple[str, str], ...]
    canonical_bytes: int
    payloads: PayloadCapture

    @property
    def consumer_graph_sha256(self) -> str:
        """Immutable native consumer/role/path/OWNER baseline, not current pixels."""
        return self.native_graph_sha256

    def summary(self) -> dict[str, Any]:
        """Fresh bounded plain facts only; native handles and arrays are excluded."""
        value = {"profile": PROFILE, "native_graph_sha256": self.native_graph_sha256,
                 "portable_graph_sha256": self.portable_graph_sha256,
                 "consumer_graph_sha256": self.consumer_graph_sha256,
                 "full_native_prefix_sha256": self.full_native_prefix_sha256,
                 "full_portable_prefix_sha256": self.full_portable_prefix_sha256,
                 "native_identity_rows": self.native_identity_rows,
                 "portable_identity_rows": [{key: item for key, item in row.items() if key not in {"pointer", "session_uid"}}
                                             for row in self.native_identity_rows],
                 "original": self.original_metadata, "snapshot": self.snapshot_metadata,
                 "workload": self.workload, "resource_facts": self.resource_facts,
                 "catalog_facts": self.catalog_facts, "canonical_stream_bytes": self.canonical_bytes,
                 "payload_facts": self.payloads.facts(), "complete_pixels_verified": True,
                 "snapshot_canonical_packed_verified": True, "original_canonical_packed_verified": True,
                 "recovery_authorized": False}
        raw = _canonical(value)
        if len(raw) > 64 * 1024:
            raise refused("PLAIN_GRAPH_SUMMARY_BUDGET")
        return json.loads(raw)  # Deep plain copy; never leak mutable retained baselines.


def _packed(reader: _Reader, image: Any) -> bytes:
    reader.check()
    if image.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")
    packed = image.packed_file
    if packed is None:
        raise refused("COMPLETE_PACKED_PAYLOAD_REQUIRED")
    reader.catalog(packed, "PackedFile")
    size = _int(packed.size, MAX_PAYLOAD_BYTES, minimum=1)
    reader.check()
    payload = packed.data
    if type(payload) is not bytes or len(payload) != size:
        raise refused("COMPLETE_PACKED_PAYLOAD_SHAPE")
    return payload


def _pixels(reader: _Reader, image: Any, width: int, height: int) -> array:
    reader.check()
    if image.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")
    if tuple(image.size) != (width, height) or image.is_float is not True or image.channels != 4:
        raise refused("IMAGE_BUFFER_METADATA_CHANGED")
    pixels = image.pixels
    if len(pixels) != width * height * 4:
        raise refused("INCOMPLETE_IMAGE_BUFFER")
    reader.check()
    values = array("f", [0.]) * (width * height * 4)
    reader.check()
    if image.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")
    pixels.foreach_get(values)
    return values


def _digest_steps(values: array, check: Callable[[], None]) -> Generator[dict[str, Any], None, str]:
    digest = hashlib.sha256()
    for start in range(0, len(values), 65_536):
        check()
        block = values[start:start + 65_536]
        if any(not math.isfinite(value) for value in block):
            raise refused("NONFINITE_IMAGE_CHANNEL")
        if sys.byteorder != "little":
            block.byteswap()
        digest.update(block)
        yield {"phase": "verifying_complete_float32_channels", "completed": min(start + 65_536, len(values)), "total": len(values)}
    return digest.hexdigest()


def _drain(steps: Generator) -> Any:
    while True:
        try:
            next(steps)
        except StopIteration as stopped:
            return stopped.value


def capture_graph_steps(bpy: Any, image_name: str | None, snapshot_name: str,
                        affected_materials: tuple[str, ...] | list[str], *, check: Callable[[], None],
                        available_memory_bytes: int, available_disk_bytes: int,
                        lifecycle_record: str | None = None) -> Generator[dict[str, Any], None, GraphCapture]:
    """Capture complete declared state after grants/path/resource preflight.

    ``check`` is the source-qualified provider-free origin/lifetime gate, not an
    arbitrary permission factory. The caller performs current canonical grants
    before entry. Live authored graph passes are synchronous; yielded work is
    private pixel validation/decoding. A final complete live recapture refuses
    manual changes while those pure steps yielded. Native reads may block.
    """
    from .tools import image_portability as storage
    from .tools.image_recovery_jobs import _decode_steps

    names = _names(image_name, snapshot_name, affected_materials)
    if lifecycle_record is not None:
        # Avoid resolving an argument as a new or foreign callback.
        expected_record = validate_lifecycle_record(lifecycle_record)
    else:
        expected_record = None
    reader = _Reader(bpy, check)
    first = _structure(reader, *names, expected_record)
    width, height = first.original_metadata["static"]["width"], first.original_metadata["static"]["height"]
    resources = validate_resource_facts(width, height, available_memory_bytes, available_disk_bytes)
    original_packed = _packed(reader, first.original)
    snapshot_packed = _packed(reader, first.snapshot)
    original_pixels = _pixels(reader, first.original, width, height)
    snapshot_pixels = _pixels(reader, first.snapshot, width, height)
    current_digest = yield from _digest_steps(original_pixels, check)
    helper_digest = yield from _digest_steps(snapshot_pixels, check)
    del snapshot_pixels
    if current_digest != helper_digest:
        raise refused("SNAPSHOT_CURRENT_CHANNELS_DIFFER")
    # This parser validates exact canonical header, offsets and every scanline;
    # its explicit payload cap is 257MiB, not the old synchronous20MiB default.
    check()
    old_values = yield from _decode_steps(original_packed, {"width": width, "height": height}, check)
    old_digest = yield from _digest_steps(old_values, check)
    del old_values
    check()
    helper_values = yield from _decode_steps(snapshot_packed, {"width": width, "height": height}, check)
    decoded_helper_digest = yield from _digest_steps(helper_values, check)
    del helper_values
    if decoded_helper_digest != current_digest:
        raise refused("SNAPSHOT_CANONICAL_CHANNELS_DIFFER")
    check()
    reader.begin_pass()
    reader.catalog(first.snapshot, "Image")
    if first.snapshot.has_data is not True:
        raise refused("TARGET_BUFFER_UNLOADED")
    reader.catalog(first.snapshot.colorspace_settings, "ColorManagedInputColorspaceSettings")
    reader.catalog(first.snapshot.packed_file, "PackedFile")
    metadata = storage._snapshot(first.snapshot, first.original, maximum_pixels=16_777_216, maximum_bytes=MAX_PAYLOAD_BYTES)
    if (metadata["source"] != "FILE" or metadata["is_float"] is not True or metadata["colorspace"] != "Non-Color"
            or metadata["alpha_mode"] != "CHANNEL_PACKED" or (metadata["width"], metadata["height"]) != (width, height)
            or metadata["pixels_sha256_float32_le"] != current_digest
            or metadata["packed_sha256"] != hashlib.sha256(snapshot_packed).hexdigest()):
        raise refused("SNAPSHOT_SCHEMA_OR_COMPLETE_HASHES_DIFFER")
    last = _structure(reader, *names, expected_record)
    if (last.native_graph_sha256 != first.native_graph_sha256 or last.native_rows != first.native_rows
            or last.original_metadata != first.original_metadata or last.snapshot_metadata != first.snapshot_metadata
            or last.original is not first.original or last.snapshot is not first.snapshot):
        raise refused("GRAPH_CHANGED_DURING_CAPTURE")
    # Re-read complete current payloads, not just sizes/dirty flags. Private
    # yields must never adopt intervening manual edits as a newer baseline.
    original_digest = hashlib.sha256(original_packed).hexdigest()
    snapshot_digest = hashlib.sha256(snapshot_packed).hexdigest()
    for image, packed_digest in ((first.original, original_digest), (first.snapshot, snapshot_digest)):
        if hashlib.sha256(_packed(reader, image)).hexdigest() != packed_digest:
            raise refused("PACKED_PAYLOAD_CHANGED_DURING_CAPTURE")
        actual = _pixels(reader, image, width, height)
        actual_digest = _drain(_digest_steps(actual, check))
        del actual
        if actual_digest != current_digest:
            raise refused("PIXELS_CHANGED_DURING_CAPTURE")
    # No provider runs between these final native reads and pure receipt creation.
    check()
    payloads = PayloadCapture(original_pixels, original_packed, snapshot_packed, current_digest,
                              original_digest, old_digest, snapshot_digest)
    volatile = {"original": first.original_metadata["volatile"], "snapshot": first.snapshot_metadata["volatile"],
                "payloads": payloads.facts()}
    prefix_native = hashlib.sha256(_canonical([first.native_graph_sha256, volatile])).hexdigest()
    prefix_portable = hashlib.sha256(_canonical([first.portable_graph_sha256, volatile])).hexdigest()
    return GraphCapture(first.original, first.snapshot, first.materials, first.objects,
                         first.native_graph_sha256, first.portable_graph_sha256, prefix_native, prefix_portable,
                         first.native_rows, first.original_metadata, first.snapshot_metadata,
                         first.workload, resources, first.catalog_facts, first.canonical_bytes, payloads)


def capture_graph(bpy: Any, image_name: str | None, snapshot_name: str,
                  affected_materials: tuple[str, ...] | list[str], *, check: Callable[[], None],
                  available_memory_bytes: int, available_disk_bytes: int,
                  lifecycle_record: str | None = None) -> GraphCapture:
    return _drain(capture_graph_steps(bpy, image_name, snapshot_name, affected_materials, check=check,
                  available_memory_bytes=available_memory_bytes, available_disk_bytes=available_disk_bytes,
                  lifecycle_record=lifecycle_record))
