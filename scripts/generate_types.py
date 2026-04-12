#!/usr/bin/env python3
"""Generate shared constants, event data types, and Go models from YAML definitions.

Per ADR-015 Phase 1 / Phase 3 / Phase 4 / Phase 5, constants and models are
split into responsibility-based packages and emitted to 9 Go modules (Phase 3)
+ 4 C# csproj (Phase 5) + 8 npm packages (Phase 4).

Outputs (Go — each directory is an independent Go module per ADR-015 Phase 3):
  - packages/game-design-constants/constants_gen.go
  - packages/game-logic-constants/constants_gen.go
  - packages/ws-constants/constants_gen.go
  - packages/shop-constants/constants_gen.go
  - packages/newsfeed-constants/constants_gen.go
  - packages/card-types/{card,card_stats,passive_effect,npc_models}_gen.go
  - packages/api-client/{deck,rest_api,ws_messages}_gen.go
  - packages/api-battle-rpc/battle_gateway_rpc_gen.go

Outputs (C# — each directory is an independent NuGet csproj per ADR-015 Phase 5;
ws / shop / newsfeed constants are NOT generated because battle does not
consume them):
  - packages/game-design-constants-dotnet/GameDesignConstants_gen.cs
    (namespace OverloadParty.GameDesignConstants)
  - packages/game-logic-constants-dotnet/GameLogicConstants_gen.cs
    (namespace OverloadParty.GameLogicConstants)
  - packages/game-state-dotnet/{EventData,GameStateView,VariantTypes}_gen.cs
    (namespace OverloadParty.GameState; also embeds cache/cards_gen.json)
  - packages/api-battle-rpc-dotnet/BattleGatewayRpc_gen.cs
    (namespace OverloadParty.ApiBattleRpc)

Outputs (TS — ADR-015 Phase 4 — 各ディレクトリが独立した npm package):
  - packages/game-design-constants-npm/src/index.ts
  - packages/game-logic-constants-npm/src/index.ts
  - packages/ws-constants-npm/src/index.ts
  - packages/shop-constants-npm/src/index.ts
  - packages/newsfeed-constants-npm/src/index.ts
  - packages/card-types-npm/src/{models,index}.ts
  - packages/game-state-npm/src/{models,eventData,variantTypes,index}.ts
  - packages/api-client-npm/src/{models,wsMessages,index}.ts

Usage:
    python3 scripts/generate_types.py
"""

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ─── Paths ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

GAME_DESIGN_YAML = DATA_DIR / "game_design_constants.yaml"
GAME_LOGIC_YAML = DATA_DIR / "game_logic_constants.yaml"
GATEWAY_WS_YAML = DATA_DIR / "gateway_ws_constants.yaml"
SHOP_YAML = DATA_DIR / "shop_constants.yaml"
NEWSFEED_YAML = DATA_DIR / "newsfeed_constants.yaml"
FACTIONS_YAML = DATA_DIR / "factions.yaml"

EVENT_SCHEMAS_YAML = DATA_DIR / "event_schemas.yaml"
MODELS_YAML = DATA_DIR / "models.yaml"

PACKAGES_DIR = ROOT / "packages"

# Go module directories (one per logical package — ADR-015 Phase 3/4 naming).
GO_GAME_DESIGN_DIR = PACKAGES_DIR / "game-design-constants"
GO_GAME_LOGIC_DIR = PACKAGES_DIR / "game-logic-constants"
GO_WS_DIR = PACKAGES_DIR / "ws-constants"
GO_SHOP_DIR = PACKAGES_DIR / "shop-constants"
GO_NEWSFEED_DIR = PACKAGES_DIR / "newsfeed-constants"
GO_CARD_TYPES_DIR = PACKAGES_DIR / "card-types"
GO_API_CLIENT_DIR = PACKAGES_DIR / "api-client"
GO_API_BATTLE_RPC_DIR = PACKAGES_DIR / "api-battle-rpc"

# Mapping of models.yaml section name → (target Go module dir, Go package name).
# Sections not listed here (e.g., game_state_view with go_skip) are not emitted.
_GO_MODELS_ROUTING = {
    "card":               (GO_CARD_TYPES_DIR,     "cardtypes"),
    "card_stats":         (GO_CARD_TYPES_DIR,     "cardtypes"),
    "passive_effect":     (GO_CARD_TYPES_DIR,     "cardtypes"),
    "npc_models":         (GO_CARD_TYPES_DIR,     "cardtypes"),
    "deck":               (GO_API_CLIENT_DIR,     "apiclient"),
    "rest_api":           (GO_API_CLIENT_DIR,     "apiclient"),
    "ws_messages":        (GO_API_CLIENT_DIR,     "apiclient"),
    "battle_gateway_rpc": (GO_API_BATTLE_RPC_DIR, "apibattle"),
}

# C# csproj directories (one per logical package — ADR-015 Phase 5 naming).
# ws / shop / newsfeed constants are NOT generated for C# because battle does
# not consume them.
DOTNET_GAME_DESIGN_DIR = PACKAGES_DIR / "game-design-constants-dotnet"
DOTNET_GAME_LOGIC_DIR = PACKAGES_DIR / "game-logic-constants-dotnet"
DOTNET_GAME_STATE_DIR = PACKAGES_DIR / "game-state-dotnet"
DOTNET_API_BATTLE_RPC_DIR = PACKAGES_DIR / "api-battle-rpc-dotnet"

# npm package directories (one per logical package — ADR-015 Phase 4 naming).
NPM_GAME_DESIGN_DIR = PACKAGES_DIR / "game-design-constants-npm"
NPM_GAME_LOGIC_DIR = PACKAGES_DIR / "game-logic-constants-npm"
NPM_WS_DIR = PACKAGES_DIR / "ws-constants-npm"
NPM_SHOP_DIR = PACKAGES_DIR / "shop-constants-npm"
NPM_NEWSFEED_DIR = PACKAGES_DIR / "newsfeed-constants-npm"
NPM_CARD_TYPES_DIR = PACKAGES_DIR / "card-types-npm"
NPM_GAME_STATE_DIR = PACKAGES_DIR / "game-state-npm"
NPM_API_CLIENT_DIR = PACKAGES_DIR / "api-client-npm"

# Mapping of models.yaml section name → target npm package directory for TS models.
# Sections not listed here are not emitted as TS (e.g., battle_gateway_rpc has ts_skip: true).
# ws_messages is emitted separately by generate_ts_ws_messages.
_TS_MODELS_ROUTING = {
    "card":            NPM_CARD_TYPES_DIR,
    "card_stats":      NPM_CARD_TYPES_DIR,
    "passive_effect":  NPM_CARD_TYPES_DIR,
    "npc_models":      NPM_CARD_TYPES_DIR,
    "game_state_view": NPM_GAME_STATE_DIR,
    "deck":            NPM_API_CLIENT_DIR,
    "rest_api":        NPM_API_CLIENT_DIR,
}

# ─── Helpers ────────────────────────────────────────────

_GENERATED_HEADER = "// Code generated by scripts/generate_types.py; DO NOT EDIT."


def _snake_to_pascal(s):
    return "".join(w.title() for w in s.split("_"))


def _camel_to_pascal(s):
    return s[0].upper() + s[1:]


def _to_pascal(value):
    """Convert a YAML value to a PascalCase identifier.

    Handles snake_case, kebab-case, lowercase, PascalCase, uppercase, and slashes.
    """
    value = value.replace("/", "")
    if "_" in value or "-" in value:
        return "".join(w.title() for w in value.replace("-", "_").split("_"))
    if value and value[0].isupper():
        return value
    return value.title() if value else value


# ─── Simple list descriptors (per category) ────────────
#
# Each tuple: (yaml_key, go_prefix, go_comment, cs_class, ts_const, ts_type, extra_union)
# extra_union is used only by TS and only for very specific cases (phases, instance_families).

GAME_DESIGN_SIMPLE = [
    ("zones", "Zone", "Zones", "Zones", "ZONES", "Zone", None),
    ("ranks", "Rank", "Ranks", "Ranks", "RANKS", "Rank", None),
    ("instance_families", "InstanceFamily", "Instance families", "InstanceFamilies", "INSTANCE_FAMILIES", "InstanceFamily", "''"),
    ("restriction_values", "Restriction", "Restriction values", "RestrictionValues", "RESTRICTION_VALUES", "Restriction", None),
    ("match_types", "MatchType", "Match types", "MatchTypes", "MATCH_TYPES", "MatchType", None),
    ("stat_types", "StatType", "Stat types", "StatTypes", "STAT_TYPES", "StatType", None),
]

GAME_LOGIC_SIMPLE = [
    ("phases", "Phase", "Phases", "Phases", "PHASES", "GamePhase", "'selecting'"),
    ("game_status", "GameStatus", "Game status", "GameStatus", "GAME_STATUS", "GameStatus", None),
    ("win_reasons", "WinReason", "Win reasons", "WinReasons", "WIN_REASONS", "WinReason", None),
    ("action_types", "ActionType", "Action types", "ActionTypes", "ACTION_TYPES", "GameActionType", None),
    ("event_types", "EventType", "Event types", "EventTypes", "EVENT_TYPES", "EventType", None),
    ("effect_durations", "EffectDuration", "Effect durations", "EffectDurations", "EFFECT_DURATIONS", "EffectDuration", None),
    ("trigger_types", "TriggerType", "Trigger types", "TriggerTypes", "TRIGGER_TYPES", "TriggerType", None),
    ("effect_ops", "EffectOp", "Effect operations", "EffectOps", "EFFECT_OPS", "EffectOp", None),
    ("buff_types", "BuffType", "Buff types", "BuffTypes", "BUFF_TYPES", "BuffType", None),
    ("buff_modes", "BuffMode", "Buff modes", "BuffModes", "BUFF_MODES", "BuffMode", None),
    ("custom_effects", "CustomEffect", "Custom effects", "CustomEffects", "CUSTOM_EFFECTS", "CustomEffect", None),
    ("effect_categories", "EffectCategory", "Effect categories", "EffectCategories", "EFFECT_CATEGORIES", "EffectCategory", None),
    ("effect_target_types", "EffectTargetType", "Effect target types", "EffectTargetTypes", "EFFECT_TARGET_TYPES", "EffectTargetType", None),
    ("player_refs", "PlayerRef", "Player references", "PlayerRefs", "PLAYER_REFS", "PlayerRef", None),
    ("use_limits", "UseLimit", "Use limits", "UseLimits", "USE_LIMITS", "UseLimit", None),
    ("guard_types", "GuardType", "Guard types", "GuardTypes", "GUARD_TYPES", "GuardType", None),
    ("selector_pick_modes", "SelectorPickMode", "Selector pick modes", "SelectorPickModes", "SELECTOR_PICK_MODES", "SelectorPickMode", None),
]

SHOP_SIMPLE = [
    ("product_types", "ProductType", "Product types", "ProductTypes", "PRODUCT_TYPES", "ProductType", None),
]

NEWSFEED_SIMPLE = [
    ("cloud_news_sources", "CloudNewsSource", "Cloud news sources", "CloudNewsSources", "CLOUD_NEWS_SOURCES", "CloudNewsSource", None),
]


# ─── Go constants: generic emitters ────────────────────
def _go_const_block(comment, prefix, values):
    """Generate a Go const block from a list of values."""
    lines = [f"// {comment}."]
    lines.append("const (")
    for v in values:
        name = f"{prefix}{_to_pascal(v)}"
        lines.append(f'\t{name} = "{v}"')
    lines.append(")")
    lines.append("")
    return lines


def _go_header(package):
    return [
        _GENERATED_HEADER,
        "",
        f"package {package}",
        "",
    ]


def _write_file(out_path, lines):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Go: game_design sub-package ───────────────────────
def generate_go_game_design(data, factions):
    """Generate constants/game_design/constants_gen.go."""
    lines = _go_header("game_design")

    # Deck size.
    iv = data["initial_values"]
    lines.append("// Deck size.")
    lines.append("const (")
    lines.append(f"\tDeckSize = {iv['deck_size']}")
    lines.append(")")
    lines.append("")

    # Factions.
    sorted_factions = sorted(factions, key=lambda f: f["sort_order"])
    lines.append("// Factions.")
    lines.append("const (")
    for f in sorted_factions:
        lines.append(f'\tFaction{f["id"]} = "{f["id"]}"')
    lines.append(")")
    lines.append("")

    selectable = [f for f in sorted_factions if f.get("is_collectible")]
    lines.append("// SelectableFactions is the list of factions players can choose.")
    lines.append("var SelectableFactions = []string{")
    for f in selectable:
        lines.append(f"\tFaction{f['id']},")
    lines.append("}")
    lines.append("")

    # FactionMetadata struct + slice + lookup map.
    lines.append("// FactionMetadata holds display and ordering information for a faction.")
    lines.append("type FactionMetadata struct {")
    lines.append("\tID            string")
    lines.append("\tShortNameJa   string")
    lines.append("\tShortNameEn   string")
    lines.append("\tFullNameJa    string")
    lines.append("\tFullNameEn    string")
    lines.append("\tIsCollectible bool")
    lines.append("\tSortOrder     int")
    lines.append("}")
    lines.append("")

    lines.append("// FactionsMetadata lists all factions in sort order.")
    lines.append("var FactionsMetadata = []FactionMetadata{")
    for f in sorted_factions:
        lines.append("\t{")
        lines.append(f'\t\tID:            "{f["id"]}",')
        lines.append(f'\t\tShortNameJa:   {json.dumps(f["short_name_ja"], ensure_ascii=False)},')
        lines.append(f'\t\tShortNameEn:   {json.dumps(f["short_name_en"], ensure_ascii=False)},')
        lines.append(f'\t\tFullNameJa:    {json.dumps(f["full_name_ja"], ensure_ascii=False)},')
        lines.append(f'\t\tFullNameEn:    {json.dumps(f["full_name_en"], ensure_ascii=False)},')
        lines.append(f'\t\tIsCollectible: {"true" if f["is_collectible"] else "false"},')
        lines.append(f'\t\tSortOrder:     {f["sort_order"]},')
        lines.append("\t},")
    lines.append("}")
    lines.append("")

    lines.append("// FactionByID looks up faction metadata by ID.")
    lines.append("var FactionByID = map[string]FactionMetadata{")
    for f in sorted_factions:
        lines.append(f'\t"{f["id"]}": FactionsMetadata[{sorted_factions.index(f)}],')
    lines.append("}")
    lines.append("")

    # Simple lists.
    for yaml_key, go_prefix, go_comment, _, _, _, _ in GAME_DESIGN_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_go_const_block(go_comment, go_prefix, values))

    # Card types visible to clients/UI. The `log` sub-category in yaml is
    # reserved for internal log cards that do not surface in player-facing
    # enums; it is intentionally excluded here.
    ct = data["card_types"]
    all_types = ct["compute"] + ct["data"] + ct["support"]
    lines.append("// Card types.")
    lines.append("const (")
    for v in all_types:
        lines.append(f'\tCardType{_to_pascal(v)} = "{v}"')
    lines.append(")")
    lines.append("")

    compute_set = ", ".join(f'CardType{_to_pascal(v)}' for v in ct["compute"])
    data_set = ", ".join(f'CardType{_to_pascal(v)}' for v in ct["data"])
    support_non_attach = [t for t in ct["support"] if t != "Attachment"]
    support_set = ", ".join(f'CardType{_to_pascal(v)}' for v in support_non_attach)

    lines.append("// IsResourceType returns true if the card type is a deployable resource (compute or data).")
    lines.append("func IsResourceType(cardType string) bool {")
    lines.append("\tswitch cardType {")
    lines.append(f"\tcase {compute_set}, {data_set}:")
    lines.append("\t\treturn true")
    lines.append("\t}")
    lines.append("\treturn false")
    lines.append("}")
    lines.append("")

    lines.append("// IsFrontendEligible returns true if the card can be placed in the frontend zone.")
    lines.append("func IsFrontendEligible(cardType string) bool {")
    lines.append("\tswitch cardType {")
    lines.append(f"\tcase {compute_set}, CardTypeObjectStorage:")
    lines.append("\t\treturn true")
    lines.append("\t}")
    lines.append("\treturn false")
    lines.append("}")
    lines.append("")

    lines.append("// IsBackendEligible returns true if the card can be placed in the backend zone.")
    lines.append("func IsBackendEligible(cardType string) bool {")
    lines.append("\tswitch cardType {")
    lines.append(f"\tcase {data_set}, {compute_set}:")
    lines.append("\t\treturn true")
    lines.append("\t}")
    lines.append("\treturn false")
    lines.append("}")
    lines.append("")

    lines.append("// IsSupportType returns true if the card goes in the support zone.")
    lines.append("func IsSupportType(cardType string) bool {")
    lines.append("\tswitch cardType {")
    lines.append(f"\tcase {support_set}:")
    lines.append("\t\treturn true")
    lines.append("\t}")
    lines.append("\treturn false")
    lines.append("}")
    lines.append("")

    lines.append("// IsAttachmentType returns true if the card is an Attachment.")
    lines.append("func IsAttachmentType(cardType string) bool {")
    lines.append("\treturn cardType == CardTypeAttachment")
    lines.append("}")
    lines.append("")

    lines.append("// RestrictionCopyCount returns the maximum number of copies allowed in a deck.")
    lines.append("func RestrictionCopyCount(restriction string) int {")
    lines.append("\tswitch restriction {")
    lines.append("\tcase RestrictionForbidden:")
    lines.append("\t\treturn 0")
    lines.append("\tcase RestrictionLimited:")
    lines.append("\t\treturn 1")
    lines.append("\tcase RestrictionSemiLimited:")
    lines.append("\t\treturn 2")
    lines.append("\tdefault:")
    lines.append("\t\treturn 3")
    lines.append("\t}")
    lines.append("}")
    lines.append("")

    _write_file(GO_GAME_DESIGN_DIR / "constants_gen.go", lines)


# ─── Go: game_logic module ─────────────────────────────
def generate_go_game_logic(data):
    lines = _go_header("game_logic")
    for yaml_key, go_prefix, go_comment, _, _, _, _ in GAME_LOGIC_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_go_const_block(go_comment, go_prefix, values))
    _write_file(GO_GAME_LOGIC_DIR / "constants_gen.go", lines)


# ─── Go: ws module ─────────────────────────────────────
def generate_go_ws(data):
    lines = _go_header("ws")
    ws = data["ws_message_types"]

    lines.append("// WS server message types.")
    lines.append("const (")
    for v in ws["server"]:
        lines.append(f'\tWSServerMsg{_to_pascal(v)} = "{v}"')
    lines.append(")")
    lines.append("")

    lines.append("// WS client message types.")
    lines.append("const (")
    for v in ws["client"]:
        lines.append(f'\tWSClientMsg{_to_pascal(v)} = "{v}"')
    lines.append(")")
    lines.append("")

    _write_file(GO_WS_DIR / "constants_gen.go", lines)


# ─── Go: shop module ───────────────────────────────────
def generate_go_shop(data):
    lines = _go_header("shop")
    for yaml_key, go_prefix, go_comment, _, _, _, _ in SHOP_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_go_const_block(go_comment, go_prefix, values))
    _write_file(GO_SHOP_DIR / "constants_gen.go", lines)


# ─── Go: newsfeed module ───────────────────────────────
def generate_go_newsfeed(data):
    lines = _go_header("newsfeed")
    for yaml_key, go_prefix, go_comment, _, _, _, _ in NEWSFEED_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_go_const_block(go_comment, go_prefix, values))
    _write_file(GO_NEWSFEED_DIR / "constants_gen.go", lines)


# ─── Generate Go (models) ──────────────────────────────
def _go_type_needs_import(type_str):
    """Detect imports required by a Go type string."""
    imports = set()
    if "time.Time" in type_str or "time." in type_str:
        imports.add("time")
    if "json.RawMessage" in type_str:
        imports.add("encoding/json")
    if "civil.Date" in type_str or "civil." in type_str:
        imports.add("cloud.google.com/go/civil")
    return imports


def _generate_go_model_file(file_def, *, out_path, package_name):
    """Generate a single *_gen.go file from a file definition."""
    lines = [
        _GENERATED_HEADER,
        "",
        f"package {package_name}",
        "",
    ]

    declared_imports = set(file_def.get("imports", []))
    for td in file_def.get("types", []):
        for field in td.get("fields", []):
            declared_imports |= _go_type_needs_import(str(field["type"]))

    if declared_imports:
        std_imports = sorted(i for i in declared_imports if "." not in i.split("/")[0])
        ext_imports = sorted(i for i in declared_imports if "." in i.split("/")[0])
        lines.append("import (")
        for imp in std_imports:
            lines.append(f'\t"{imp}"')
        if std_imports and ext_imports:
            lines.append("")
        for imp in ext_imports:
            lines.append(f'\t"{imp}"')
        lines.append(")")
        lines.append("")

    for ta in file_def.get("type_aliases", []):
        lines.append(f"type {ta['name']} {ta['base']}")
    if file_def.get("type_aliases"):
        lines.append("")

    for cgroup in file_def.get("constants", []):
        ctype = cgroup["type"]
        lines.append("const (")
        for cv in cgroup["values"]:
            lines.append(f'\t{cv["name"]} {ctype} = "{cv["value"]}"')
        lines.append(")")
        lines.append("")

    for td in file_def.get("types", []):
        if td.get("comment"):
            lines.append(f"// {td['comment']}")
        lines.append(f"type {td['name']} struct {{")

        fields = td.get("fields", [])
        if fields:
            max_name_len = max(len(f["name"]) for f in fields)
            max_type_len = max(len(str(f["type"])) for f in fields)

        for field in fields:
            fname = field["name"]
            ftype = str(field["type"])
            tags = []
            if "json" in field:
                tags.append(f'json:"{field["json"]}"')
            if "db" in field:
                tags.append(f'db:"{field["db"]}"')
            tag_str = " ".join(tags)

            name_pad = " " * (max_name_len - len(fname) + 1)
            type_pad = " " * (max_type_len - len(ftype) + 1)

            if tag_str:
                line = f"\t{fname}{name_pad}{ftype}{type_pad}`{tag_str}`"
            else:
                line = f"\t{fname}{name_pad}{ftype}"

            if field.get("comment"):
                line += f" // {field['comment']}"
            lines.append(line)

        lines.append("}")
        lines.append("")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def generate_go_models():
    """Generate *_gen.go model files from models.yaml.

    Each models.yaml section is routed to a target Go module based on
    _GO_MODELS_ROUTING. Sections not in the routing table (or with
    go_skip: true) are not emitted as Go code.

    Returns a dict of {module_dir: [emitted_section_names]} for logging.
    """
    with open(MODELS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    emitted = {}

    for file_def in data["files"]:
        file_target = file_def.get("target", "both")
        if file_target != "both" and file_target != "gateway":
            continue
        if file_def.get("go_skip"):
            continue

        name = file_def["name"]
        route = _GO_MODELS_ROUTING.get(name)
        if route is None:
            # No Go output for this section (e.g., deliberately skipped
            # or not yet assigned to a module).
            continue

        module_dir, package_name = route
        out_path = module_dir / f"{name}_gen.go"
        _generate_go_model_file(file_def, out_path=out_path, package_name=package_name)
        emitted.setdefault(module_dir, []).append(name)

    return emitted


# ─── C# constants: generic emitters ────────────────────
def _cs_static_class(class_name, values, indent="    "):
    """Generate a C# static class with string constants."""
    lines = [f"public static class {class_name}"]
    lines.append("{")
    for v in values:
        name = _to_pascal(v)
        lines.append(f'{indent}public const string {name} = "{v}";')
    lines.append("}")
    lines.append("")
    return lines


def _cs_header(namespace):
    return [
        _GENERATED_HEADER,
        "",
        f"namespace {namespace};",
        "",
    ]


# ─── C#: game_design namespace ─────────────────────────
def generate_csharp_game_design(data, factions):
    lines = _cs_header("OverloadParty.GameDesignConstants")

    # Deck size wrapper class.
    iv = data["initial_values"]
    lines.append("public static class InitialValues")
    lines.append("{")
    lines.append(f"    public const int DeckSize = {iv['deck_size']};")
    lines.append("}")
    lines.append("")

    sorted_factions = sorted(factions, key=lambda f: f["sort_order"])

    lines.append("public static class Factions")
    lines.append("{")
    for f in sorted_factions:
        lines.append(f'    public const string {f["id"]} = "{f["id"]}";')
    lines.append("}")
    lines.append("")

    selectable = [f for f in sorted_factions if f.get("is_collectible")]
    lines.append("public static class SelectableFactions")
    lines.append("{")
    lines.append("    public static readonly string[] All = [")
    for f in selectable:
        lines.append(f"        Factions.{f['id']},")
    lines.append("    ];")
    lines.append("}")
    lines.append("")

    lines.append("public record FactionMetadata(")
    lines.append("    string Id,")
    lines.append("    string ShortNameJa,")
    lines.append("    string ShortNameEn,")
    lines.append("    string FullNameJa,")
    lines.append("    string FullNameEn,")
    lines.append("    bool IsCollectible,")
    lines.append("    int SortOrder")
    lines.append(");")
    lines.append("")

    lines.append("public static class FactionsMetadata")
    lines.append("{")
    lines.append("    public static readonly FactionMetadata[] All = [")
    for f in sorted_factions:
        is_col = "true" if f["is_collectible"] else "false"
        ja_short = json.dumps(f["short_name_ja"], ensure_ascii=False)
        en_short = json.dumps(f["short_name_en"], ensure_ascii=False)
        ja_full = json.dumps(f["full_name_ja"], ensure_ascii=False)
        en_full = json.dumps(f["full_name_en"], ensure_ascii=False)
        lines.append(
            f'        new FactionMetadata("{f["id"]}", {ja_short}, {en_short}, '
            f'{ja_full}, {en_full}, {is_col}, {f["sort_order"]}),'
        )
    lines.append("    ];")
    lines.append("")
    lines.append("    public static readonly System.Collections.Generic.Dictionary<string, FactionMetadata> ById =")
    lines.append("        System.Linq.Enumerable.ToDictionary(All, m => m.Id);")
    lines.append("}")
    lines.append("")

    # Simple list classes.
    for yaml_key, _, _, cs_class, _, _, _ in GAME_DESIGN_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_cs_static_class(cs_class, values))

    # Card types visible to clients/UI. The `log` sub-category is reserved
    # for internal log cards and is intentionally excluded.
    ct = data["card_types"]
    all_types = ct["compute"] + ct["data"] + ct["support"]
    lines.append("public static class CardTypes")
    lines.append("{")
    for v in all_types:
        lines.append(f'    public const string {_to_pascal(v)} = "{v}";')
    lines.append("")

    compute_refs = ", ".join(_to_pascal(v) for v in ct["compute"])
    data_refs = ", ".join(_to_pascal(v) for v in ct["data"])
    support_non_attach = [t for t in ct["support"] if t != "Attachment"]
    support_refs = ", ".join(_to_pascal(v) for v in support_non_attach)

    lines.append(f"    public static readonly string[] ComputeTypes = [{compute_refs}];")
    lines.append(f"    public static readonly string[] DataTypes = [{data_refs}];")
    lines.append(f"    public static readonly string[] SupportTypes = [{support_refs}];")
    lines.append("")

    lines.append("    public static bool IsResourceType(string cardType) =>")
    lines.append("        System.Array.IndexOf(ComputeTypes, cardType) >= 0 || System.Array.IndexOf(DataTypes, cardType) >= 0;")
    lines.append("")
    lines.append("    public static bool IsFrontendEligible(string cardType) =>")
    lines.append("        System.Array.IndexOf(ComputeTypes, cardType) >= 0 || cardType == ObjectStorage;")
    lines.append("")
    lines.append("    public static bool IsBackendEligible(string cardType) =>")
    lines.append("        System.Array.IndexOf(DataTypes, cardType) >= 0 || System.Array.IndexOf(ComputeTypes, cardType) >= 0;")
    lines.append("")
    lines.append("    public static bool IsSupportType(string cardType) =>")
    lines.append("        System.Array.IndexOf(SupportTypes, cardType) >= 0;")
    lines.append("")
    lines.append("    public static bool IsAttachmentType(string cardType) =>")
    lines.append("        cardType == Attachment;")
    lines.append("")

    lines.append("    public static string GetCategory(string cardType)")
    lines.append("    {")
    lines.append("        if (System.Array.IndexOf(ComputeTypes, cardType) >= 0) return \"compute\";")
    lines.append("        if (System.Array.IndexOf(DataTypes, cardType) >= 0) return \"data\";")
    lines.append("        if (System.Array.IndexOf(SupportTypes, cardType) >= 0 || cardType == Attachment) return \"support\";")
    lines.append('        return "unknown";')
    lines.append("    }")
    lines.append("}")
    lines.append("")

    lines.append("public static class RestrictionHelper")
    lines.append("{")
    lines.append("    public static int CopyCount(string restriction) => restriction switch")
    lines.append("    {")
    lines.append("        RestrictionValues.Forbidden => 0,")
    lines.append("        RestrictionValues.Limited => 1,")
    lines.append("        RestrictionValues.SemiLimited => 2,")
    lines.append("        _ => 3,")
    lines.append("    };")
    lines.append("}")
    lines.append("")

    _write_file(DOTNET_GAME_DESIGN_DIR / "GameDesignConstants_gen.cs", lines)


# ─── C#: game_logic namespace ──────────────────────────
def generate_csharp_game_logic(data):
    lines = _cs_header("OverloadParty.GameLogicConstants")
    for yaml_key, _, _, cs_class, _, _, _ in GAME_LOGIC_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_cs_static_class(cs_class, values))
    _write_file(DOTNET_GAME_LOGIC_DIR / "GameLogicConstants_gen.cs", lines)


# ws / shop / newsfeed C# generators were removed — battle does not consume
# these constants, so no C# package is published for them (ADR-015 Phase 5).


# ─── Generate C# (event data) ──────────────────────────
_CS_TYPE_MAP = {
    "string": "string",
    "int": "int",
    "long": "long",
    "bool": "bool",
    "string[]": "List<string>",
}

_CS_NULLABLE_DEFAULTS = {
    "string": "string?",
    "int": "int?",
    "long": "long?",
    "bool": "bool?",
    "string[]": "List<string>?",
}


def generate_csharp_event_data(schemas, *, out_path, namespace="OverloadParty.GameState"):
    """Generate EventData_gen.cs."""
    cs_out = Path(out_path)

    lines = [
        _GENERATED_HEADER,
        "",
        f"namespace {namespace};",
        "",
        "/// <summary>Marker interface for all EventData records. Used to constrain GameEvent.EventData type.</summary>",
        "public interface IEventData { }",
        "",
    ]

    for event_type, fields in schemas.items():
        if event_type.startswith("_"):
            continue

        class_name = f"{_snake_to_pascal(event_type)}EventData"
        lines.append(f"public class {class_name} : IEventData")
        lines.append("{")

        required_fields = []
        optional_fields = []

        for raw_key, raw_type in fields.items():
            optional = raw_key.endswith("?")
            key = raw_key.rstrip("?")
            cs_prop = _snake_to_pascal(key) if "_" in key else _camel_to_pascal(key)

            if optional:
                cs_type = _CS_NULLABLE_DEFAULTS[raw_type]
                optional_fields.append((key, cs_prop, cs_type, raw_type))
            else:
                cs_type = _CS_TYPE_MAP[raw_type]
                init = ' = "";' if raw_type == "string" else " = [];" if raw_type == "string[]" else ""
                required_fields.append((key, cs_prop, cs_type, init))
                lines.append(f"    public required {cs_type} {cs_prop} {{ get; init; }}{init}")

        for key, cs_prop, cs_type, raw_type in optional_fields:
            lines.append(f"    public {cs_type} {cs_prop} {{ get; init; }}")

        lines.append("}")
        lines.append("")

    cs_out.parent.mkdir(parents=True, exist_ok=True)
    with open(cs_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Generate C# (game state view) ───────────────────
_GO_TO_CS_TYPE = {
    "string": "string",
    "int": "int",
    "int64": "long",
    "bool": "bool",
    "time.Time": "DateTime",
    "json.RawMessage": "JsonElement?",
}


def _go_to_cs_type(go_type):
    """Convert a Go type string to a C# type string."""
    is_pointer = go_type.startswith("*")
    base = go_type.lstrip("*")

    if base.startswith("[]*"):
        elem = base[3:]
        cs_elem = _GO_TO_CS_TYPE.get(elem, elem)
        return f"{cs_elem}?[]"

    if base.startswith("[]"):
        elem = base[2:]
        cs_elem = _GO_TO_CS_TYPE.get(elem, elem)
        return f"{cs_elem}[]"

    cs_base = _GO_TO_CS_TYPE.get(base, base)

    if is_pointer:
        return f"{cs_base}?"

    return cs_base


def generate_csharp_game_state_view(*, out_path, namespace="OverloadParty.GameState"):
    """Generate GameStateView_gen.cs from the game_state_view section of models.yaml."""
    with open(MODELS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    file_def = None
    for fd in data["files"]:
        if fd["name"] == "game_state_view":
            file_def = fd
            break

    if file_def is None:
        print("WARNING: game_state_view not found in models.yaml, skipping C# generation", file=sys.stderr)
        return

    cs_out = Path(out_path)

    lines = [
        _GENERATED_HEADER,
        "",
        f"namespace {namespace};",
        "",
    ]

    for td in file_def.get("types", []):
        name = td["name"]
        if td.get("comment"):
            lines.append(f"/// <summary>{td['comment']}</summary>")
        lines.append(f"public class {name}")
        lines.append("{")

        for field in td.get("fields", []):
            go_type = str(field["type"])
            json_tag = str(field.get("json", ""))
            has_omitempty = json_tag.endswith(",omitempty")
            cs_type = _go_to_cs_type(go_type)
            fname = field["name"]

            is_custom_ref = cs_type not in _GO_TO_CS_TYPE.values() and not cs_type.endswith("?") and not cs_type.endswith("[]")

            if go_type.startswith("*"):
                lines.append(f"    public {cs_type} {fname} {{ get; init; }}")
            elif go_type.startswith("[]"):
                if has_omitempty:
                    lines.append(f"    public {cs_type}? {fname} {{ get; init; }}")
                else:
                    lines.append(f"    public {cs_type} {fname} {{ get; init; }} = [];")
            elif is_custom_ref:
                lines.append(f"    public required {cs_type} {fname} {{ get; init; }}")
            elif cs_type == "string":
                lines.append(f'    public {cs_type} {fname} {{ get; init; }} = "";')
            else:
                lines.append(f"    public {cs_type} {fname} {{ get; init; }}")

        lines.append("}")
        lines.append("")

    cs_out.parent.mkdir(parents=True, exist_ok=True)
    with open(cs_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Generate C# (battle ↔ gateway RPC envelope) ──────
_GO_TO_CS_ENVELOPE_TYPE = {
    "string": "string",
    "int": "int",
    "int64": "long",
    "bool": "bool",
    "time.Time": "DateTime",
    "json.RawMessage": "JsonElement",
}


def _go_to_cs_envelope_type(go_type):
    """Convert a Go type string to a C# type string for envelope types."""
    is_pointer = go_type.startswith("*")
    base = go_type.lstrip("*")

    if base.startswith("[]"):
        elem = base[2:]
        cs_elem = _GO_TO_CS_ENVELOPE_TYPE.get(elem, elem)
        return f"List<{cs_elem}>"

    cs_base = _GO_TO_CS_ENVELOPE_TYPE.get(base, base)

    if is_pointer:
        return f"{cs_base}?"

    return cs_base


def generate_csharp_battle_gateway_rpc(*, out_path, namespace="OverloadParty.ApiBattleRpc"):
    """Generate BattleGatewayRpc_gen.cs from the battle_gateway_rpc section."""
    with open(MODELS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    file_def = None
    for fd in data["files"]:
        if fd["name"] == "battle_gateway_rpc":
            file_def = fd
            break

    if file_def is None:
        print("WARNING: battle_gateway_rpc not found in models.yaml, skipping C# generation", file=sys.stderr)
        return

    cs_out = Path(out_path)

    lines = [
        _GENERATED_HEADER,
        "",
        "using System.Text.Json;",
        "using System.Text.Json.Serialization;",
        "",
        f"namespace {namespace};",
        "",
    ]

    for td in file_def.get("types", []):
        name = td["name"]
        is_request = name.endswith("Request")

        if td.get("comment"):
            lines.append(f"/// <summary>{td['comment']}</summary>")

        if is_request:
            fields = td.get("fields", [])
            if not fields:
                lines.append(f"public record {name}();")
                lines.append("")
                continue

            lines.append(f"public record {name}(")
            for i, field in enumerate(fields):
                go_type = str(field["type"])
                json_tag = str(field.get("json", ""))
                json_key = json_tag.split(",")[0]
                cs_type = _go_to_cs_envelope_type(go_type)
                fname = field["name"]
                trailing = "," if i < len(fields) - 1 else ");"
                lines.append(f'    [property: JsonPropertyName("{json_key}")] {cs_type} {fname}{trailing}')
            lines.append("")
        else:
            lines.append(f"public class {name}")
            lines.append("{")
            for field in td.get("fields", []):
                go_type = str(field["type"])
                json_tag = str(field.get("json", ""))
                json_key = json_tag.split(",")[0]
                has_omitempty = json_tag.endswith(",omitempty")
                cs_type = _go_to_cs_envelope_type(go_type)
                fname = field["name"]

                lines.append(f'    [JsonPropertyName("{json_key}")]')
                if go_type.startswith("*"):
                    lines.append(f"    public {cs_type} {fname} {{ get; init; }}")
                elif go_type.startswith("[]"):
                    if has_omitempty:
                        lines.append(f"    public {cs_type}? {fname} {{ get; init; }}")
                    else:
                        lines.append(f"    public {cs_type} {fname} {{ get; init; }} = [];")
                elif cs_type == "string":
                    lines.append(f'    public {cs_type} {fname} {{ get; init; }} = "";')
                else:
                    lines.append(f"    public {cs_type} {fname} {{ get; init; }}")
            lines.append("}")
            lines.append("")

    cs_out.parent.mkdir(parents=True, exist_ok=True)
    with open(cs_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── TS constants: generic emitters ────────────────────
def _ts_const_array(const_name, type_name, values, extra_union=None):
    """Generate a TS as-const array with union type."""
    lines = []
    lines.append(f"export const {const_name} = {json.dumps(values)} as const;")
    if extra_union:
        lines.append(f"export type {type_name} = (typeof {const_name})[number] | {extra_union};")
    else:
        lines.append(f"export type {type_name} = (typeof {const_name})[number];")
    lines.append("")
    return lines


def _ts_header():
    return [
        _GENERATED_HEADER,
        "",
    ]


def _write_ts_index(out_path, module_names):
    """Write a barrel index.ts that re-exports from sibling modules."""
    lines = [_GENERATED_HEADER]
    for name in module_names:
        lines.append(f"export * from './{name}';")
    _write_file(Path(out_path), lines)


# ─── TS: gameDesign.ts ─────────────────────────────────
def generate_ts_game_design(data, factions):
    lines = _ts_header()

    for yaml_key, _, _, _, ts_const, ts_type, extra_union in GAME_DESIGN_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_ts_const_array(ts_const, ts_type, values, extra_union=extra_union))

    # Card types visible to clients/UI. The `log` sub-category is reserved
    # for internal log cards and is intentionally excluded.
    ct = data["card_types"]
    all_card_types = ct["compute"] + ct["data"] + ct["support"]
    lines.append(f"export const CARD_TYPES = {json.dumps(all_card_types)} as const;")
    lines.append("export type CardType = (typeof CARD_TYPES)[number];")
    lines.append("")

    compute_set = json.dumps(ct["compute"])
    data_set = json.dumps(ct["data"])
    lines.append(f"const COMPUTE_TYPES: ReadonlySet<string> = new Set({compute_set});")
    lines.append(f"const DATA_TYPES: ReadonlySet<string> = new Set({data_set});")
    lines.append("")

    lines.append("/** Returns true if the card type is a deployable resource (compute or data). */")
    lines.append("export function isResourceType(cardType: string): boolean {")
    lines.append("  return COMPUTE_TYPES.has(cardType) || DATA_TYPES.has(cardType);")
    lines.append("}")
    lines.append("")

    lines.append("/** Returns true if the card can be placed in the frontend zone. */")
    lines.append("export function isFrontendEligible(cardType: string): boolean {")
    lines.append("  return COMPUTE_TYPES.has(cardType) || cardType === 'ObjectStorage';")
    lines.append("}")
    lines.append("")

    lines.append("/** Returns true if the card can be placed in the backend zone. */")
    lines.append("export function isBackendEligible(cardType: string): boolean {")
    lines.append("  return DATA_TYPES.has(cardType) || COMPUTE_TYPES.has(cardType);")
    lines.append("}")
    lines.append("")

    support_types = [t for t in ct["support"] if t != "Attachment"]
    lines.append("/** Returns true if the card goes in the support zone (Platform, Strategy, Incident, Reactive). */")
    lines.append("export function isSupportType(cardType: string): boolean {")
    if support_types:
        support_cases = " || ".join(f"cardType === '{t}'" for t in support_types)
        lines.append(f"  return {support_cases};")
    else:
        lines.append("  return false;")
    lines.append("}")
    lines.append("")

    lines.append("/** Returns true if the card is an Attachment (attaches to resources, not support zone). */")
    lines.append("export function isAttachmentType(cardType: string): boolean {")
    lines.append("  return cardType === 'Attachment';")
    lines.append("}")
    lines.append("")

    lines.append("/** Returns the maximum number of copies allowed in a deck for a given restriction. */")
    lines.append("export function restrictionCopyCount(restriction: Restriction): number {")
    lines.append("  switch (restriction) {")
    lines.append("    case 'forbidden': return 0;")
    lines.append("    case 'limited': return 1;")
    lines.append("    case 'semi_limited': return 2;")
    lines.append("    case 'unlimited': return 3;")
    lines.append("    default: return 3;")
    lines.append("  }")
    lines.append("}")
    lines.append("")

    # Factions.
    sorted_factions = sorted(factions, key=lambda f: f["sort_order"])
    all_faction_ids = [f["id"] for f in sorted_factions]
    selectable_ids = [f["id"] for f in sorted_factions if f.get("is_collectible")]

    lines.append(f"export const FACTIONS = {json.dumps(all_faction_ids)} as const;")
    lines.append(f"export const SELECTABLE_FACTIONS = {json.dumps(selectable_ids)} as const;")
    lines.append("export type FactionId = (typeof SELECTABLE_FACTIONS)[number];")
    lines.append("")

    lines.append("export interface FactionMetadata {")
    lines.append("  id: string;")
    lines.append("  shortNameJa: string;")
    lines.append("  shortNameEn: string;")
    lines.append("  fullNameJa: string;")
    lines.append("  fullNameEn: string;")
    lines.append("  isCollectible: boolean;")
    lines.append("  sortOrder: number;")
    lines.append("}")
    lines.append("")

    lines.append("export const FACTIONS_METADATA: readonly FactionMetadata[] = [")
    for f in sorted_factions:
        entry = {
            "id": f["id"],
            "shortNameJa": f["short_name_ja"],
            "shortNameEn": f["short_name_en"],
            "fullNameJa": f["full_name_ja"],
            "fullNameEn": f["full_name_en"],
            "isCollectible": f["is_collectible"],
            "sortOrder": f["sort_order"],
        }
        # Emit with JS-style boolean lowercase (json.dumps already produces true/false).
        lines.append(f"  {json.dumps(entry, ensure_ascii=False)},")
    lines.append("];")
    lines.append("")

    lines.append("export const FACTION_BY_ID: Record<string, FactionMetadata> = {")
    for f in sorted_factions:
        lines.append(f'  "{f["id"]}": FACTIONS_METADATA[{sorted_factions.index(f)}],')
    lines.append("};")
    lines.append("")

    # Initial values.
    iv = data["initial_values"]
    lines.append("export const INITIAL_VALUES = {")
    for key, val in iv.items():
        camel = re.sub(r'_([a-z])', lambda m: m.group(1).upper(), key)
        lines.append(f"  {camel}: {val},")
    lines.append("} as const;")
    lines.append("")

    _write_file(NPM_GAME_DESIGN_DIR / "src" / "index.ts", lines)


# ─── TS: game-logic-constants-npm ──────────────────────
def generate_ts_game_logic(data):
    lines = _ts_header()
    for yaml_key, _, _, _, ts_const, ts_type, extra_union in GAME_LOGIC_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_ts_const_array(ts_const, ts_type, values, extra_union=extra_union))
    _write_file(NPM_GAME_LOGIC_DIR / "src" / "index.ts", lines)


# ─── TS: ws-constants-npm ──────────────────────────────
def generate_ts_ws(data):
    lines = _ts_header()
    ws_types = data["ws_message_types"]
    lines.append(f"export const WS_SERVER_MSG_TYPES = {json.dumps(ws_types['server'])} as const;")
    lines.append("export type WSServerMsgType = (typeof WS_SERVER_MSG_TYPES)[number];")
    lines.append("")
    lines.append(f"export const WS_CLIENT_MSG_TYPES = {json.dumps(ws_types['client'])} as const;")
    lines.append("export type WSClientMsgType = (typeof WS_CLIENT_MSG_TYPES)[number];")
    lines.append("")
    _write_file(NPM_WS_DIR / "src" / "index.ts", lines)


# ─── TS: shop-constants-npm ────────────────────────────
def generate_ts_shop(data):
    lines = _ts_header()
    for yaml_key, _, _, _, ts_const, ts_type, extra_union in SHOP_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_ts_const_array(ts_const, ts_type, values, extra_union=extra_union))
    _write_file(NPM_SHOP_DIR / "src" / "index.ts", lines)


# ─── TS: newsfeed-constants-npm ────────────────────────
def generate_ts_newsfeed(data):
    lines = _ts_header()
    for yaml_key, _, _, _, ts_const, ts_type, extra_union in NEWSFEED_SIMPLE:
        values = data.get(yaml_key)
        if values is None:
            continue
        lines.extend(_ts_const_array(ts_const, ts_type, values, extra_union=extra_union))
    _write_file(NPM_NEWSFEED_DIR / "src" / "index.ts", lines)


# ─── Generate TypeScript (event data) ──────────────────
_TS_TYPE_MAP = {
    "string": "string",
    "int": "number",
    "long": "number",
    "bool": "boolean",
    "string[]": "string[]",
}


def generate_ts_event_data(schemas, *, out_path):
    """Generate eventData.ts."""
    ts_out = Path(out_path)

    lines = [
        _GENERATED_HEADER,
        "",
    ]

    type_names = []

    for event_type, fields in schemas.items():
        if event_type.startswith("_"):
            continue

        type_name = f"{_snake_to_pascal(event_type)}EventData"
        type_names.append((event_type, type_name))

        lines.append(f"export interface {type_name} {{")
        for raw_key, raw_type in fields.items():
            optional = raw_key.endswith("?")
            key = raw_key.rstrip("?")
            ts_type = _TS_TYPE_MAP[raw_type]
            opt = "?" if optional else ""
            lines.append(f"  {key}{opt}: {ts_type};")
        lines.append("}")
        lines.append("")

    lines.append("export interface EventDataMap {")
    for event_type, type_name in type_names:
        lines.append(f"  {event_type}: {type_name};")
    lines.append("}")
    lines.append("")

    ts_out.parent.mkdir(parents=True, exist_ok=True)
    with open(ts_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Generate TypeScript (WS messages) ─────────────────
_GO_TO_TS_TYPE = {
    "string": "string",
    "int": "number",
    "int64": "number",
    "bool": "boolean",
    "json.RawMessage": "Record<string, unknown>",
}


def generate_ts_ws_messages(*, out_path):
    """Generate wsMessages.ts from the ws_messages section of models.yaml."""
    with open(MODELS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    ws_file = None
    for file_def in data["files"]:
        if file_def["name"] == "ws_messages":
            ws_file = file_def
            break

    if ws_file is None:
        print("WARNING: ws_messages not found in models.yaml, skipping TS generation", file=sys.stderr)
        return

    ts_out = Path(out_path)

    lines = [
        _GENERATED_HEADER,
        "",
    ]

    ws_imports: dict[str, list[str]] = {}
    for imp in ws_file.get("ts_imports", []):
        from_path = imp["from"]
        for name in imp["names"]:
            ws_imports.setdefault(from_path, []).append(name)

    for from_path, names in sorted(ws_imports.items()):
        sorted_names = sorted(set(names))
        lines.append(f"import type {{ {', '.join(sorted_names)} }} from '{from_path}';")
    if ws_imports:
        lines.append("")

    for td in ws_file.get("types", []):
        name = td["name"]
        if td.get("comment"):
            lines.append(f"/** {td['comment']} */")
        lines.append(f"export interface {name} {{")
        for field in td.get("fields", []):
            json_tag = field["json"]
            optional = json_tag.endswith(",omitempty")
            json_key = json_tag.split(",")[0]
            go_type = str(field["type"])
            ts_type = _GO_TO_TS_TYPE.get(go_type, "unknown")
            if "ts_type" in field:
                ts_type = field["ts_type"]
            if "ts_optional" in field:
                optional = field["ts_optional"]
            opt = "?" if optional else ""
            lines.append(f"  {json_key}{opt}: {ts_type};")
        lines.append("}")
        lines.append("")

    ts_out.parent.mkdir(parents=True, exist_ok=True)
    with open(ts_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Generate TypeScript (models) ─────────────────────────
_GO_TO_TS_MODEL_TYPE = {
    "string": "string",
    "int": "number",
    "int64": "number",
    "bool": "boolean",
    "time.Time": "string",
    "json.RawMessage": "Record<string, unknown>",
    "interface{}": "unknown",
    "map[string]interface{}": "Record<string, unknown>",
    "civil.Date": "string",
}


def _go_to_ts_model_field(go_type, json_tag, type_map=None, *, nullable_as_optional=False):
    """Convert a Go type + json tag to a TS type string and optional flag."""
    if type_map is None:
        type_map = _GO_TO_TS_MODEL_TYPE
    optional = json_tag.endswith(",omitempty")
    json_key = json_tag.split(",")[0]

    is_pointer = go_type.startswith("*")
    base_type = go_type.lstrip("*")

    if base_type.startswith("[]*"):
        elem = base_type[3:]
        ts_elem = type_map.get(elem, elem)
        ts_type = f"({ts_elem} | null)[]"
        return json_key, ts_type, optional

    if base_type.startswith("[]"):
        elem = base_type[2:]
        ts_elem = type_map.get(elem, elem)
        ts_type = f"{ts_elem}[]"
        return json_key, ts_type, optional

    if base_type.startswith("map["):
        ts_type = type_map.get(base_type, "Record<string, unknown>")
        return json_key, ts_type, optional

    ts_base = type_map.get(base_type, base_type)

    if is_pointer:
        if optional:
            return json_key, ts_base, True
        elif nullable_as_optional:
            return json_key, ts_base, True
        else:
            return json_key, f"{ts_base} | null", False

    return json_key, ts_base, optional


def generate_ts_models():
    """Generate models.ts files from models.yaml sections, routed per _TS_MODELS_ROUTING.

    Each target npm package gets one models.ts that bundles all sections routed to it.
    Returns a dict of {package_dir: [emitted_section_names]} for logging.
    """
    with open(MODELS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    alias_map = dict(_GO_TO_TS_MODEL_TYPE)
    for file_def in data["files"]:
        for ta in file_def.get("type_aliases", []):
            base = ta["base"]
            alias_map[ta["name"]] = _GO_TO_TS_MODEL_TYPE.get(base, base)

    # Group file_defs by target npm package directory.
    files_by_pkg: dict[Path, list[dict]] = {}
    for file_def in data["files"]:
        file_target = file_def.get("target", "both")
        if file_target not in ("both", "gateway", "api"):
            continue
        if file_def["name"] == "ws_messages":
            continue
        if file_def.get("ts_skip"):
            continue
        pkg_dir = _TS_MODELS_ROUTING.get(file_def["name"])
        if pkg_dir is None:
            continue
        files_by_pkg.setdefault(pkg_dir, []).append(file_def)

    emitted: dict[Path, list[str]] = {}

    for pkg_dir, file_defs in files_by_pkg.items():
        lines = [
            _GENERATED_HEADER,
            "",
        ]

        ts_imports: dict[str, list[str]] = {}
        for file_def in file_defs:
            for imp in file_def.get("ts_imports", []):
                from_path = imp["from"]
                for name in imp["names"]:
                    ts_imports.setdefault(from_path, []).append(name)

        for from_path, names in sorted(ts_imports.items()):
            sorted_names = sorted(set(names))
            lines.append(f"import type {{ {', '.join(sorted_names)} }} from '{from_path}';")
        if ts_imports:
            lines.append("")

        for file_def in file_defs:
            file_nullable_as_optional = file_def.get("nullable_as_optional", False)

            for ta in file_def.get("ts_type_aliases", []):
                lines.append(f"export type {ta['name']} = {ta['value']};")
            if file_def.get("ts_type_aliases"):
                lines.append("")

            for td in file_def.get("types", []):
                name = td["name"]
                if td.get("comment"):
                    lines.append(f"/** {td['comment']} */")
                lines.append(f"export interface {name} {{")
                for field in td.get("fields", []):
                    go_type = str(field["type"])
                    json_tag = field["json"]
                    json_key, ts_type, optional = _go_to_ts_model_field(
                        go_type, json_tag, alias_map,
                        nullable_as_optional=file_nullable_as_optional,
                    )
                    if "ts_type" in field:
                        ts_type = field["ts_type"]
                    if "ts_optional" in field:
                        optional = field["ts_optional"]
                    opt = "?" if optional else ""
                    lines.append(f"  {json_key}{opt}: {ts_type};")
                lines.append("}")
                lines.append("")

        out_path = pkg_dir / "src" / "models.ts"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")

        emitted[pkg_dir] = [fd["name"] for fd in file_defs]

    return emitted


# ─── Generate C# (variant types) ─────────────────────────
def generate_csharp_variant_types(variant_types, *, out_path, namespace="OverloadParty.GameState"):
    """Generate VariantTypes_gen.cs from variant_types in models.yaml."""
    cs_out = Path(out_path)

    lines = [
        _GENERATED_HEADER,
        "",
        f"namespace {namespace};",
        "",
    ]

    for vt in variant_types:
        name = vt["name"]
        discriminator = vt["discriminator"]
        disc_prop = _snake_to_pascal(discriminator)

        if vt.get("comment"):
            lines.append(f"/// <summary>{vt['comment']}</summary>")

        lines.append(f"public class {name}")
        lines.append("{")

        lines.append(f'    public required string {disc_prop} {{ get; init; }} = "";')

        seen = {}
        for variant in vt["variants"]:
            for field in variant.get("fields", []):
                fname = field["name"]
                if fname in seen:
                    continue
                cs_prop = _camel_to_pascal(fname)
                raw_type = field["type"]
                cs_type = _CS_NULLABLE_DEFAULTS[raw_type]
                seen[fname] = (cs_prop, cs_type)

        for cs_prop, cs_type in seen.values():
            lines.append(f"    public {cs_type} {cs_prop} {{ get; init; }}")

        lines.append("}")
        lines.append("")

    cs_out.parent.mkdir(parents=True, exist_ok=True)
    with open(cs_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Generate TypeScript (variant types) ─────────────────
def generate_ts_variant_types(variant_types, *, out_path):
    """Generate variantTypes.ts from variant_types in models.yaml.

    Current variant types only reference game_design symbols (InstanceFamily, Rank),
    so imports are hardcoded to @kenyamaneko/overload-party-game-design-constants.
    """
    ts_out = Path(out_path)

    ref_types: set[str] = set()
    for vt in variant_types:
        for variant in vt.get("variants", []):
            for field in variant.get("fields", []):
                ref = field.get("ref")
                if ref:
                    ref_types.add(ref)

    lines = [
        _GENERATED_HEADER,
        "",
    ]

    if ref_types:
        sorted_refs = sorted(ref_types)
        lines.append(
            f"import type {{ {', '.join(sorted_refs)} }} from '@kenyamaneko/overload-party-game-design-constants';"
        )
        lines.append("")

    for vt in variant_types:
        name = vt["name"]
        discriminator = vt["discriminator"]

        if vt.get("comment"):
            lines.append(f"/** {vt['comment']} */")

        variant_lines = []
        for variant in vt["variants"]:
            value = variant["value"]
            fields = [f"{discriminator}: '{value}'"]
            for field in variant.get("fields", []):
                fname = field["name"]
                ref = field.get("ref")
                ts_type = ref if ref else _TS_TYPE_MAP[field["type"]]
                opt = "?" if field.get("optional") else ""
                fields.append(f"{fname}{opt}: {ts_type}")
            variant_lines.append("  | { " + "; ".join(fields) + " }")

        lines.append(f"export type {name} =")
        for vl in variant_lines:
            lines.append(vl)
        lines[-1] = lines[-1] + ";"
        lines.append("")

    ts_out.parent.mkdir(parents=True, exist_ok=True)
    with open(ts_out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


# ─── Update API reference docs (marker-based) ────────
DOCS_DIR = ROOT / "docs" / "architecture"

_DOC_TYPE_MAP = {
    "string": "string",
    "int": "number",
    "int64": "number",
    "bool": "boolean",
    "time.Time": "string (ISO 8601)",
    "json.RawMessage": "object",
    "interface{}": "unknown",
    "map[string]interface{}": "object",
}


def _doc_type(go_type):
    """Convert a Go type string to a human-readable doc type."""
    is_pointer = go_type.startswith("*")
    base = go_type.lstrip("*")

    if base.startswith("[]*"):
        elem = base[3:]
        return f"({_DOC_TYPE_MAP.get(elem, elem)} | null)[]"
    if base.startswith("[]"):
        elem = base[2:]
        return f"{_DOC_TYPE_MAP.get(elem, elem)}[]"

    doc_base = _DOC_TYPE_MAP.get(base, base)
    if is_pointer:
        return f"{doc_base}?"
    return doc_base


_JSON_PLACEHOLDER = {
    "string": '"string"',
    "int": "0",
    "int64": "0",
    "bool": "false",
    "time.Time": '"2006-01-02T15:04:05Z"',
    "json.RawMessage": "{}",
    "interface{}": "null",
    "map[string]interface{}": "{}",
}


def _json_placeholder(go_type):
    """Return a JSON placeholder value string for a Go type."""
    is_pointer = go_type.startswith("*")
    base = go_type.lstrip("*")

    if base.startswith("[]"):
        return "[]"
    if base.startswith("map["):
        return "{}"
    if is_pointer:
        return "null"
    return _JSON_PLACEHOLDER.get(base, '"{}"'.format(base))


def _generate_field_table(type_def):
    """Generate a Markdown field table + JSON skeleton for a type definition."""
    doc_fields = []
    for field in type_def.get("fields", []):
        if "doc" not in field:
            continue
        json_tag = field["json"]
        json_key = json_tag.split(",")[0]
        go_type = str(field["type"])
        doc_fields.append((json_key, go_type, field["doc"]))

    if not doc_fields:
        return None

    json_entries = []
    for json_key, go_type, doc in doc_fields:
        json_entries.append(f'  "{json_key}": {_json_placeholder(go_type)} // {doc}')
    json_body = ",\n".join(json_entries)
    return f"```jsonc\n{{\n{json_body}\n}}\n```"


def update_doc_field_tables(doc_path):
    """Replace marker-delimited sections in a Markdown file with generated field tables."""
    doc_file = Path(doc_path)
    if not doc_file.exists():
        return False

    with open(MODELS_YAML, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    type_map = {}
    for file_def in data.get("files", []):
        for td in file_def.get("types", []):
            type_map[td["name"]] = td

    with open(doc_file, "r", encoding="utf-8") as f:
        content = f.read()

    marker_re = re.compile(
        r"(<!-- BEGIN GENERATED: (\w+) -->)\n(.*?)(<!-- END GENERATED: \2 -->)",
        re.DOTALL,
    )

    def replacer(match):
        begin_tag = match.group(1)
        type_name = match.group(2)
        end_tag = match.group(4)
        td = type_map.get(type_name)
        if td is None:
            print(f"WARNING: type '{type_name}' not found in models.yaml, skipping marker in {doc_file.name}", file=sys.stderr)
            return match.group(0)
        table = _generate_field_table(td)
        if table is None:
            return match.group(0)
        return f"{begin_tag}\n{table}\n{end_tag}"

    new_content = marker_re.sub(replacer, content)
    if new_content == content:
        return False

    with open(doc_file, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


# ─── Main ──────────────────────────────────────────────
def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    # Post ADR-015 Phase 6/7, this repo only owns newsfeed constants. Cross-
    # cutting constants + card/models/api/ws generators moved to their owning
    # repos (common / card / battle / gateway). The legacy helpers further up
    # in this file remain only because they share utility code used by the
    # newsfeed path; they are not invoked from main() anymore.
    newsfeed = _load_yaml(NEWSFEED_YAML)

    generate_go_newsfeed(newsfeed)
    print("Generated → packages/newsfeed-constants/constants_gen.go", file=sys.stderr)

    generate_ts_newsfeed(newsfeed)
    print("Generated → packages/newsfeed-constants-npm/src/index.ts", file=sys.stderr)


if __name__ == "__main__":
    main()
