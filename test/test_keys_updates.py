"""
test/test_keys_updates.py - Tests for keys_router updates:
  - Prefix stripping (resqml20.obj_, eml20.obj_, etc.)
  - Alphabetical sorting by label/title
  - Multi-select type support (comma-separated types)
  - Category grouping for type lists
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient
from app.main import app


# ─────────────────────────────────────────────────────────────────────────────
# Test data helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fake_objects_with_prefixes():
    """Return fake objects with various RESQML/EML prefixes."""
    return [
        {
            "uuid": "uuid-1",
            "title": "resqml20.obj_TopVolantis",
            "uri": "eml:///dataspace('demo-drogon')/resqml20.obj_Grid2dRepresentation('uuid-1')",
        },
        {
            "uuid": "uuid-2",
            "title": "resqml22.obj_BaseVolantis",
            "uri": "eml:///dataspace('demo-drogon')/resqml22.obj_Grid2dRepresentation('uuid-2')",
        },
        {
            "uuid": "uuid-3",
            "title": "eml23.obj_ContinuousProperty",
            "uri": "eml:///dataspace('demo-drogon')/eml23.obj_ContinuousProperty('uuid-3')",
        },
        {
            "uuid": "uuid-4",
            "title": "eml20.obj_DiscreteProperty",
            "uri": "eml:///dataspace('demo-drogon')/eml20.obj_DiscreteProperty('uuid-4')",
        },
    ]


def _fake_types():
    """Return fake types for category grouping."""
    return [
        {"name": "resqml20.obj_Grid2dRepresentation", "count": 5},
        {"name": "resqml20.obj_IjkGridRepresentation", "count": 2},
        {"name": "resqml20.obj_ContinuousProperty", "count": 12},
        {"name": "resqml20.obj_HorizonInterpretation", "count": 3},
        {"name": "resqml20.obj_WellboreTrajectoryRepresentation", "count": 7},
        {"name": "eml20.obj_EpcExternalPartReference", "count": 8},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Tests for prefix stripping and alphabetical sorting
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keys_objects_strips_prefixes():
    """Test that /keys/objects.json strips RESQML/EML type prefixes."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        # Mock the osdu.list_resources call
        mock_osdu.list_resources = AsyncMock(return_value=_fake_objects_with_prefixes())
        
        response = client.get(
            "/keys/objects.json?ds=demo-drogon&typ=resqml20.obj_Grid2dRepresentation"
        )
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify prefixes are stripped from all titles (results are sorted alphabetically)
        titles = [item["title"] for item in items]
        assert titles == ["BaseVolantis", "ContinuousProperty", "DiscreteProperty", "TopVolantis"]
        
        # Verify no prefixes remain
        for item in items:
            assert not item["title"].startswith(("resqml", "eml"))


@pytest.mark.asyncio
async def test_keys_objects_sorts_alphabetically():
    """Test that /keys/objects.json sorts results alphabetically."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        # Create objects with titles that will test alphabetical sorting
        unordered_objects = [
            {"uuid": "z-uuid", "title": "resqml20.obj_Zebra", "uri": "..."},
            {"uuid": "a-uuid", "title": "resqml20.obj_Apple", "uri": "..."},
            {"uuid": "m-uuid", "title": "resqml20.obj_Mango", "uri": "..."},
        ]
        mock_osdu.list_resources = AsyncMock(return_value=unordered_objects)
        
        response = client.get(
            "/keys/objects.json?ds=demo-drogon&typ=resqml20.obj_Grid2dRepresentation"
        )
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify alphabetical sorting (after prefix stripping)
        titles = [item["title"] for item in items]
        assert titles == ["Apple", "Mango", "Zebra"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests for multi-select type support
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keys_objects_multi_select_types():
    """Test that /keys/objects.json supports comma-separated types."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        # Mock separate calls for each type
        mock_osdu.list_resources = AsyncMock(side_effect=[
            [{"uuid": "grid-1", "title": "resqml20.obj_Grid1", "uri": "..."}],
            [{"uuid": "prop-1", "title": "resqml20.obj_Property1", "uri": "..."}],
        ])
        
        response = client.get(
            "/keys/objects.json?ds=demo-drogon&typ=resqml20.obj_Grid2dRepresentation,resqml20.obj_ContinuousProperty"
        )
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify both types returned and aggregated
        assert len(items) == 2
        assert items[0]["uuid"] == "grid-1"
        assert items[1]["uuid"] == "prop-1"


@pytest.mark.asyncio
async def test_keys_objects_multi_select_aggregates():
    """Test that multi-select types aggregate and sort results."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        # Return objects for two different types
        grid_objects = [
            {"uuid": "g2", "title": "resqml20.obj_Grid2", "uri": "..."},
        ]
        prop_objects = [
            {"uuid": "p1", "title": "resqml20.obj_Property1", "uri": "..."},
            {"uuid": "p3", "title": "resqml20.obj_Property3", "uri": "..."},
        ]
        mock_osdu.list_resources = AsyncMock(side_effect=[grid_objects, prop_objects])
        
        response = client.get(
            "/keys/objects.json?ds=demo-drogon&typ=resqml20.obj_Grid2dRepresentation,resqml20.obj_ContinuousProperty"
        )
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify aggregation and alphabetical sorting
        assert len(items) == 3
        titles = [item["title"] for item in items]
        # After stripping prefixes: Grid2, Property1, Property3
        assert titles == sorted(titles, key=str.lower)


# ─────────────────────────────────────────────────────────────────────────────
# Tests for category grouping
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keys_types_includes_categories():
    """Test that /keys/types.json includes category information."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        mock_osdu.list_types = AsyncMock(return_value=_fake_types())
        
        response = client.get("/keys/types.json?ds=demo-drogon&source=live")
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify all items have a category field
        for item in items:
            assert "category" in item
            assert item["category"] in [
                "Grid", "Surface", "Well", "Property", "Stratigraphy", 
                "Organization", "CRS", "Provenance", "Reference", "Other"
            ]
        
        # Verify specific categorizations
        categories = {item["name"]: item["category"] for item in items}
        assert categories["resqml20.obj_Grid2dRepresentation"] == "Surface"
        assert categories["resqml20.obj_IjkGridRepresentation"] == "Grid"
        assert categories["resqml20.obj_ContinuousProperty"] == "Property"
        assert categories["resqml20.obj_HorizonInterpretation"] == "Stratigraphy"
        assert categories["resqml20.obj_WellboreTrajectoryRepresentation"] == "Well"


@pytest.mark.asyncio
async def test_keys_types_grouping_coverage():
    """Test that all types are properly categorized."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        all_types = [
            {"name": "resqml20.obj_Grid2dRepresentation", "count": 1},
            {"name": "resqml20.obj_IjkGridRepresentation", "count": 1},
            {"name": "resqml20.obj_TriangulatedSetRepresentation", "count": 1},
            {"name": "resqml20.obj_PointSetRepresentation", "count": 1},
            {"name": "resqml20.obj_PolylineSetRepresentation", "count": 1},
            {"name": "resqml20.obj_WellboreTrajectoryRepresentation", "count": 1},
            {"name": "resqml20.obj_ContinuousProperty", "count": 1},
            {"name": "resqml20.obj_HorizonInterpretation", "count": 1},
        ]
        mock_osdu.list_types = AsyncMock(return_value=all_types)
        
        response = client.get("/keys/types.json?ds=demo-drogon&source=live")
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify no "Other" category unless necessary
        other_count = sum(1 for item in items if item["category"] == "Other")
        # Most types should be properly categorized
        assert other_count <= 1


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests combining multiple features
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keys_objects_prefix_stripping_all_versions():
    """Test prefix stripping for all RESQML/EML versions."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        objects = [
            {"uuid": "v1", "title": "resqml20.obj_Type1", "uri": "..."},
            {"uuid": "v2", "title": "resqml22.obj_Type2", "uri": "..."},
            {"uuid": "v3", "title": "resqml23.obj_Type3", "uri": "..."},
            {"uuid": "v4", "title": "eml20.obj_Type4", "uri": "..."},
            {"uuid": "v5", "title": "eml21.obj_Type5", "uri": "..."},
            {"uuid": "v6", "title": "eml22.obj_Type6", "uri": "..."},
            {"uuid": "v7", "title": "eml23.obj_Type7", "uri": "..."},
        ]
        mock_osdu.list_resources = AsyncMock(return_value=objects)
        
        response = client.get(
            "/keys/objects.json?ds=demo-drogon&typ=resqml20.obj_IjkGridRepresentation"
        )
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        
        # Verify all prefixes are stripped
        titles = [item["title"] for item in items]
        assert titles == ["Type1", "Type2", "Type3", "Type4", "Type5", "Type6", "Type7"]


@pytest.mark.asyncio
async def test_keys_objects_empty_results():
    """Test that empty results are handled gracefully."""
    client = TestClient(app)
    
    with patch('app.keys_router.osdu') as mock_osdu:
        mock_osdu.list_resources = AsyncMock(return_value=[])
        
        response = client.get(
            "/keys/objects.json?ds=demo-drogon&typ=resqml20.obj_IjkGridRepresentation"
        )
        
        assert response.status_code == 200
        data = response.json()
        items = data.get("items", [])
        assert len(items) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
