"""Stable city and source identifiers for the third city group."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CitySource:
    slug: str
    display_name: str
    epsg: int
    source_type: str
    source_url: str
    collection_mode: str
    candidate_scope: str

    def export(self) -> dict:
        return asdict(self)


CITIES = {
    "essen": CitySource(
        "essen",
        "Essen",
        25832,
        "police_native_archive",
        "https://essen.polizei.nrw/presse/pressemitteilungen",
        "online",
        "essen_candidate",
    ),
    "dresden": CitySource(
        "dresden",
        "Dresden",
        25833,
        "official_media_archive",
        "https://medienservice.sachsen.de/medien/?search%5Binstitution_ids%5D%5B%5D=10997",
        "offline",
        "dresden_candidate",
    ),
    "hannover": CitySource(
        "hannover",
        "Hannover",
        25832,
        "police_linked_newsroom",
        "https://www.presseportal.de/blaulicht/nr/66841",
        "online",
        "hannover_candidate",
    ),
    "nuremberg": CitySource(
        "nuremberg",
        "Nuremberg",
        25832,
        "police_native_archive",
        "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/",
        "offline",
        "nuremberg_candidate",
    ),
}
