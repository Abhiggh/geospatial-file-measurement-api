import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from app.services.storage import validate_shapefile_archive


def test_valid_shapefile_zip(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    shp_path = source_dir / "zones.shp"
    gdf = gpd.GeoDataFrame(
        {"name": ["zone"]},
        geometry=[Polygon([(77, 12), (77.01, 12), (77.01, 12.01), (77, 12.01)])],
        crs="EPSG:4326",
    )
    gdf.to_file(shp_path, driver="ESRI Shapefile", engine="pyogrio")

    zip_path = tmp_path / "zones.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in source_dir.iterdir():
            zf.write(file, file.name)

    assert Path(validate_shapefile_archive(zip_path)).suffix.lower() == ".shp"


def test_zip_path_traversal_rejected(tmp_path):
    import pytest
    from fastapi import HTTPException

    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.shp", b"bad")
    with pytest.raises(HTTPException) as exc:
        validate_shapefile_archive(zip_path)
    assert exc.value.status_code == 400
