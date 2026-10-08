import geopandas as gpd
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.services.geospatial import iter_measurements


def test_wgs84_polygon_is_projected_and_measured():
    gdf = gpd.GeoDataFrame(
        {"name": ["square"]},
        geometry=[Polygon([(77.0, 12.0), (77.01, 12.0), (77.01, 12.01), (77.0, 12.01)])],
        crs="EPSG:4326",
    )
    result = next(iter_measurements(gdf))
    assert result.measurement_status == "MEASURED"
    assert result.measurement_type == "area"
    assert result.measurement_unit == "m²"
    assert result.measurement_value is not None
    assert 1_000_000 < result.measurement_value < 1_500_000
    assert result.measurement_crs is not None
    assert result.measurement_crs != "EPSG:4326"


def test_line_is_measured_in_meters():
    gdf = gpd.GeoDataFrame(
        {"name": ["line"]},
        geometry=[LineString([(77.0, 12.0), (77.01, 12.0)])],
        crs="EPSG:4326",
    )
    result = next(iter_measurements(gdf))
    assert result.measurement_status == "MEASURED"
    assert result.measurement_type == "length"
    assert result.measurement_unit == "m"
    assert 900 < result.measurement_value < 1300


def test_point_needs_no_measurement():
    gdf = gpd.GeoDataFrame({"name": ["point"]}, geometry=[Point(77, 12)], crs="EPSG:4326")
    result = next(iter_measurements(gdf))
    assert result.measurement_status == "NOT_REQUIRED"
    assert result.measurement_value is None


def test_unsupported_geometry_is_graceful():
    gdf = gpd.GeoDataFrame(
        {"name": ["collection"]},
        geometry=[GeometryCollection([Point(77, 12), LineString([(77, 12), (77.01, 12)])])],
        crs="EPSG:4326",
    )
    result = next(iter_measurements(gdf))
    assert result.measurement_status == "UNSUPPORTED_GEOMETRY"
    assert result.measurement_value is None


def test_missing_crs_does_not_calculate_metric_measurement():
    gdf = gpd.GeoDataFrame(
        {"name": ["square"]},
        geometry=[Polygon([(77.0, 12.0), (77.01, 12.0), (77.01, 12.01), (77.0, 12.01)])],
    )
    result = next(iter_measurements(gdf))
    assert result.measurement_status == "MISSING_CRS"
    assert result.measurement_value is None
