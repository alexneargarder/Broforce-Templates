"""Tests for project_types module - type registry and lookups."""
from broforce_tools.project_types import (
    PROJECT_TYPES,
    get_all_metadata_patterns,
    get_display_names,
    get_type_names,
)


class TestProjectTypes:
    def test_type_names(self):
        names = get_type_names()
        assert "mod" in names
        assert "bro" in names
        assert "wardrobe" in names

    def test_display_names(self):
        names = get_display_names()
        assert "Mod" in names
        assert "Bro" in names
        assert "Wardrobe" in names

    def test_type_names_and_display_names_same_length(self):
        assert len(get_type_names()) == len(get_display_names())

    def test_metadata_patterns(self):
        patterns = get_all_metadata_patterns()
        assert "Info.json" in patterns
        assert "*.mod.json" in patterns
        assert "*.fa.json" in patterns
        assert "*.ac.json" in patterns

    def test_all_types_have_required_keys(self):
        required_keys = [
            "display_name", "template_dir_name", "class_prefix",
            "metadata_patterns", "install_subdir", "has_code",
        ]
        for type_key, type_info in PROJECT_TYPES.items():
            for key in required_keys:
                assert key in type_info, f"{type_key} missing key: {key}"

    def test_mod_installs_to_mods(self):
        assert PROJECT_TYPES["mod"]["install_subdir"] == "Mods"

    def test_bro_installs_to_bromaker(self):
        assert PROJECT_TYPES["bro"]["install_subdir"] == "BroMaker_Storage"

    def test_wardrobe_installs_to_wardrobes(self):
        assert PROJECT_TYPES["wardrobe"]["install_subdir"] == "DM_Wardrobes"

    def test_wardrobe_has_no_code(self):
        assert not PROJECT_TYPES["wardrobe"]["has_code"]

    def test_wardrobe_depends_on_dressermod(self):
        assert "DresserMod" in PROJECT_TYPES["wardrobe"]["extra_dependencies"]
