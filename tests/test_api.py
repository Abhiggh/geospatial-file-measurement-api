from app.services.processing import process_job
from conftest import write_square_kml


def test_upload_then_process_kml(client, tmp_path):
    # Keep uploads inside the isolated pytest directory.
    import app.services.storage as storage
    import app.services.processing as processing

    storage.settings.storage_dir = tmp_path / "storage"
    processing.settings.storage_dir = tmp_path / "storage"
    storage.ensure_storage_dirs()

    kml = tmp_path / "sample.kml"
    write_square_kml(kml)

    with kml.open("rb") as handle:
        response = client.post("/api/files/", files={"file": ("sample.kml", handle, "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 202, response.text
    file_id = response.json()["id"]

    process_job(file_id)

    info = client.get(f"/api/files/{file_id}/")
    assert info.status_code == 200
    body = info.json()
    assert body["status"] == "COMPLETED"
    assert body["feature_count"] == 3
    assert body["successful_measurements"] == 2
    assert body["failed_features"] == 0

    measurements = client.get(f"/api/files/{file_id}/measurements/?page=1&page_size=10")
    assert measurements.status_code == 200
    items = measurements.json()["items"]
    assert len(items) == 3
    assert items[0]["measurement_status"] == "MEASURED"


def test_rejects_unsupported_extension(client, tmp_path):
    bad = tmp_path / "data.txt"
    bad.write_text("not geospatial", encoding="utf-8")
    with bad.open("rb") as handle:
        response = client.post("/api/files/", files={"file": ("data.txt", handle, "text/plain")})
    assert response.status_code == 415


def test_upload_then_process_shapefile_zip(client, tmp_path):
    import zipfile
    import geopandas as gpd
    from shapely.geometry import Polygon

    import app.services.processing as processing
    import app.services.storage as storage

    storage.settings.storage_dir = tmp_path / "storage"
    processing.settings.storage_dir = tmp_path / "storage"
    storage.ensure_storage_dirs()

    source_dir = tmp_path / "shp"
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
        for p in source_dir.iterdir():
            zf.write(p, p.name)

    with zip_path.open("rb") as handle:
        response = client.post("/api/files/", files={"file": ("zones.zip", handle, "application/zip")})
    assert response.status_code == 202, response.text
    file_id = response.json()["id"]

    processing.process_job(file_id)
    info = client.get(f"/api/files/{file_id}/").json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 1
    assert info["successful_measurements"] == 1

    result = client.get(f"/api/files/{file_id}/measurements/?include_geometry=true").json()
    assert result["items"][0]["geometry"]["type"] == "Polygon"
