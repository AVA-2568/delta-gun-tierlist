"""Unit tests for the gunsmith weapon modification system."""

import pytest
from src.engine.gunsmith import (
    MAINSTREAM_BUILDS,
    get_all_builds,
    get_detailed_build,
    DetailedWeaponBuild,
)
from src.models import WeaponBuild


def test_mainstream_builds_coverage():
    assert len(MAINSTREAM_BUILDS) >= 12
    for gun_id, build in MAINSTREAM_BUILDS.items():
        assert build.gun_id == gun_id
        # In-game share code format: {name}-烽火地带-{code}
        assert "烽火地带" in build.build_code
        assert len(build.build_code.split("-")) >= 3
        assert build.total_mod_cost > 0
        assert len(build.attachments) >= 4


def test_get_all_builds():
    builds = get_all_builds()
    assert len(builds) >= 12
    assert all(isinstance(b, WeaponBuild) for b in builds)
    assert all(b.mod_cost > 0 for b in builds)


def test_get_detailed_build():
    m4_build = get_detailed_build("m4a1")
    assert m4_build is not None
    assert isinstance(m4_build, DetailedWeaponBuild)
    assert m4_build.gun_name == "M4A1突击步枪"
    assert "M4A1突击步枪-烽火地带" in m4_build.build_code
    assert m4_build.total_mod_cost == 71000
    assert len(m4_build.attachments) == 6

    # Non-existent gun returns None
    assert get_detailed_build("unknown_gun_xyz") is None
