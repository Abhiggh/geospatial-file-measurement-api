from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from ..models import MeasurementStatus


SUPPORTED_LINE_TYPES = {"LineString", "MultiLineString"}
SUPPORTED_POLYGON_TYPES = {"Polygon", "MultiPolygon"}


@dataclass(slots=True)
class MeasurementResult:
    feature_index: int
    geometry_type: str
    source_crs: str | None
    measurement_crs: str | None
    measurement_type: str | None
    measurement_value: float | None
    measurement_unit: str | None
    measurement_status: str
    properties: dict[str, Any]
    geometry_geojson: dict[str, Any] | None
    error_message: str | None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    try:
        return value.item()
    except Exception:
        return str(value)


def _source_crs_text(crs: Any) -> str | None:
    if crs is None:
        return None
    try:
        return CRS.from_user_input(crs).to_string()
    except Exception:
        return str(crs)


def _local_measurement_crs(geometry: BaseGeometry, source_crs: CRS) -> CRS:
    if source_crs.is_projected:
        return source_crs

    single = gpd.GeoSeries([geometry], crs=source_crs)
    try:
        estimated = single.estimate_utm_crs()
        if estimated is not None:
            return CRS.from_user_input(estimated)
    except Exception:
        pass

    centroid = geometry.centroid
    lon, lat = float(centroid.x), float(centroid.y)
    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
        # Local Lambert Azimuthal Equal Area fallback. This is a projected CRS
        # centered on the feature and is especially useful outside UTM bounds.
        return CRS.from_proj4(
            f"+proj=laea +lat_0={lat:.8f} +lon_0={lon:.8f} +datum=WGS84 +units=m +no_defs"
        )
    raise ValueError("Geometry centroid is outside valid geographic coordinate ranges.")


def _geometry_type(geometry: BaseGeometry | None) -> str:
    return geometry.geom_type if geometry is not None else "Unknown"


def read_geospatial_file(path: str, source_type: str) -> gpd.GeoDataFrame:
    if source_type == "zip":
        raise ValueError("ZIP archives must be extracted before reading.")
    if source_type == "kml":
        return gpd.read_file(path, driver="KML", engine="pyogrio")
    raise ValueError(f"Unsupported source type: {source_type}")


def read_shapefile(path: str) -> gpd.GeoDataFrame:
    return gpd.read_file(path, engine="pyogrio")


def _measurement_for_geometry(geometry: BaseGeometry, source_crs: CRS) -> tuple[str, float, str, CRS]:
    measurement_crs = _local_measurement_crs(geometry, source_crs)
    projected = gpd.GeoSeries([geometry], crs=source_crs).to_crs(measurement_crs).iloc[0]
    geometry_type = projected.geom_type
    if geometry_type in SUPPORTED_POLYGON_TYPES:
        return "area", float(projected.area), "m²", measurement_crs
    if geometry_type in SUPPORTED_LINE_TYPES:
        return "length", float(projected.length), "m", measurement_crs
    raise TypeError(f"Unsupported geometry type: {geometry_type}")


def iter_measurements(gdf: gpd.GeoDataFrame):
    source_crs = CRS.from_user_input(gdf.crs) if gdf.crs is not None else None
    source_crs_text = _source_crs_text(gdf.crs)

    for idx, row in gdf.iterrows():
        geometry = row.geometry
        props = {str(key): _json_safe(value) for key, value in row.drop(labels=["geometry"]).to_dict().items()}
        geometry_json = None
        if geometry is not None and not geometry.is_empty:
            try:
                geometry_json = _json_safe(mapping(geometry))
            except Exception:
                geometry_json = None

        gtype = _geometry_type(geometry)
        if geometry is None or geometry.is_empty:
            yield MeasurementResult(
                feature_index=int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx)),
                geometry_type=gtype,
                source_crs=source_crs_text,
                measurement_crs=None,
                measurement_type=None,
                measurement_value=None,
                measurement_unit=None,
                measurement_status=MeasurementStatus.INVALID_GEOMETRY.value,
                properties=props,
                geometry_geojson=geometry_json,
                error_message="Geometry is null or empty.",
            )
            continue

        if gtype == "Point" or gtype == "MultiPoint":
            yield MeasurementResult(
                feature_index=int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx)),
                geometry_type=gtype,
                source_crs=source_crs_text,
                measurement_crs=None,
                measurement_type=None,
                measurement_value=None,
                measurement_unit=None,
                measurement_status=MeasurementStatus.NOT_REQUIRED.value,
                properties=props,
                geometry_geojson=geometry_json,
                error_message=None,
            )
            continue

        if gtype not in SUPPORTED_LINE_TYPES | SUPPORTED_POLYGON_TYPES:
            yield MeasurementResult(
                feature_index=int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx)),
                geometry_type=gtype,
                source_crs=source_crs_text,
                measurement_crs=None,
                measurement_type=None,
                measurement_value=None,
                measurement_unit=None,
                measurement_status=MeasurementStatus.UNSUPPORTED_GEOMETRY.value,
                properties=props,
                geometry_geojson=geometry_json,
                error_message=f"Measurement is not supported for geometry type {gtype}.",
            )
            continue

        if source_crs is None:
            yield MeasurementResult(
                feature_index=int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx)),
                geometry_type=gtype,
                source_crs=None,
                measurement_crs=None,
                measurement_type="area" if "Polygon" in gtype else "length",
                measurement_value=None,
                measurement_unit="m²" if "Polygon" in gtype else "m",
                measurement_status=MeasurementStatus.MISSING_CRS.value,
                properties=props,
                geometry_geojson=geometry_json,
                error_message="Source CRS is missing; a metric measurement cannot be calculated safely.",
            )
            continue

        try:
            measurement_type, value, unit, measurement_crs = _measurement_for_geometry(geometry, source_crs)
            yield MeasurementResult(
                feature_index=int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx)),
                geometry_type=gtype,
                source_crs=source_crs_text,
                measurement_crs=measurement_crs.to_string(),
                measurement_type=measurement_type,
                measurement_value=value,
                measurement_unit=unit,
                measurement_status=MeasurementStatus.MEASURED.value,
                properties=props,
                geometry_geojson=geometry_json,
                error_message=None,
            )
        except Exception as exc:
            yield MeasurementResult(
                feature_index=int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx)),
                geometry_type=gtype,
                source_crs=source_crs_text,
                measurement_crs=None,
                measurement_type="area" if "Polygon" in gtype else "length",
                measurement_value=None,
                measurement_unit="m²" if "Polygon" in gtype else "m",
                measurement_status=MeasurementStatus.MEASUREMENT_ERROR.value,
                properties=props,
                geometry_geojson=geometry_json,
                error_message=str(exc),
            )


def measurement_to_dict(result: MeasurementResult) -> dict[str, Any]:
    return {
        "feature_index": result.feature_index,
        "geometry_type": result.geometry_type,
        "source_crs": result.source_crs,
        "measurement_crs": result.measurement_crs,
        "measurement_type": result.measurement_type,
        "measurement_value": result.measurement_value,
        "measurement_unit": result.measurement_unit,
        "measurement_status": result.measurement_status,
        "properties": result.properties,
        "geometry": result.geometry_geojson,
        "error_message": result.error_message,
    }
