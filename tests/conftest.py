from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing = True

    import app.services.processing as processing
    monkeypatch.setattr(processing, "SessionLocal", TestingSessionLocal)
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.state.testing = False
    engine.dispose()


def write_square_kml(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Test Area</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>77.00,12.00,0 77.01,12.00,0 77.01,12.01,0 77.00,12.01,0 77.00,12.00,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Test Line</name>
      <LineString>
        <coordinates>77.00,12.00,0 77.01,12.00,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Test Point</name>
      <Point><coordinates>77.00,12.00,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>""",
        encoding="utf-8",
    )
