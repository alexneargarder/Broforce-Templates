"""Project type definitions for broforce-tools."""

PROJECT_TYPES = {
    "mod": {
        "display_name": "Mod",
        "template_dir_name": "Mod Template",
        "class_prefix": "ModTemplate",
        "metadata_patterns": ["Info.json"],
        "version_file_label": "Info.json",
        "file_patterns": ["*.csproj", "*.cs", "*.sln", "*.json", "*.xml"],
        "install_subdir": "Mods",
        "has_code": True,
        "extra_dependencies": [],
    },
    "bro": {
        "display_name": "Bro",
        "template_dir_name": "Bro Template",
        "class_prefix": "BroTemplate",
        "metadata_patterns": ["*.mod.json"],
        "version_file_label": ".mod.json",
        "file_patterns": ["*.csproj", "*.cs", "*.sln", "*.json"],
        "install_subdir": "BroMaker_Storage",
        "has_code": True,
        "extra_dependencies": [],
    },
    "wardrobe": {
        "display_name": "Wardrobe",
        "template_dir_name": "Wardrobe Template",
        "class_prefix": "WardrobeTemplate",
        "metadata_patterns": ["*.fa.json", "*.ac.json"],
        "version_file_label": None,
        "file_patterns": ["*.json"],
        "install_subdir": "DM_Wardrobes",
        "has_code": False,
        "extra_dependencies": ["DresserMod"],
    },
}


def get_type_names() -> list[str]:
    return list(PROJECT_TYPES.keys())


def get_display_names() -> list[str]:
    return [t["display_name"] for t in PROJECT_TYPES.values()]


def get_all_metadata_patterns() -> list[str]:
    patterns = []
    for t in PROJECT_TYPES.values():
        patterns.extend(t["metadata_patterns"])
    return patterns
