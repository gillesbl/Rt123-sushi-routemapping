#!/usr/bin/env python3
"""
Sushi Delivery Route Optimizer

Reads "Overzicht Bestellingen.xlsx" with delivery orders, filters for deliveries
('Leveren'), assigns orders to 3 delivery cars (Den Haag area, Rotterdam+Utrecht,
Amsterdam), and optimizes each car's route using TSP (Travelling Salesman Problem).

Usage:
    python optimize_routes.py --input "Overzicht bestellingen.xlsx" --start-time 12:00 --dropoff-time 5

Args:
    --input:        Path to Excel file with delivery orders
    --start-time:   Start driving time in HH:MM format (default: 12:00)
    --dropoff-time:  Minutes per dropoff/delivery (default: 5)
    --output-dir:   Directory for output CSV files (default: ./output)
"""

import argparse
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from ortools.constraint_solver import routing_enums_pb2, pywrapcp


# ── Configuration ──────────────────────────────────────────────────────────

DEPOT_ADDRESS = "Brinckhorstlaan, Den Haag, Netherlands"
DEPOT_LABEL = "Leger des Heils, Brinckhorstlaan, Den Haag"

# City assignments per car
CAR_ASSIGNMENTS = {
    "Car 1 - Den Haag": [
        "Den Haag", "Delft", "Zoetermeer", "Katwijk", "Leiden",
        "Rijswijk", "Voorburg", "Wassenaar", "Wateringen", "Nootdorp",
        "Leidschendam", "Santpoort Zuid",
    ],
    "Car 2 - Rotterdam & Utrecht": [
        "Rotterdam", "Utrecht", "Gouda", "Dordrecht", "Amersfoort",
        "Badhoevedorp", "Schiedam",
    ],
    "Car 3 - Amsterdam": [
        "Amsterdam", "Haarlem", "Hilversum", "Almere",
    ],
}

# Average driving speed in km/h (urban delivery driving)
AVG_SPEED_KMH = 40

# ── Address Parsing ────────────────────────────────────────────────────────

# Known Dutch cities/towns for extraction from freeform addresses
KNOWN_CITIES = [
    "Den Haag", "Amsterdam", "Rotterdam", "Utrecht", "Delft",
    "Rijswijk", "Voorburg", "Wassenaar", "Wateringen", "Nootdorp",
    "Leidschendam", "Leiden", "Zoetermeer", "Katwijk",
    "Haarlem", "Hilversum", "Almere",
    "Gouda", "Dordrecht", "Amersfoort", "Schiedam",
    "Badhoevedorp", "Santpoort Zuid",
]

# Dutch postcode regex: 4 digits + optional space + 2 letters
POSTCODE_RE = re.compile(r'\b(\d{4})\s*([A-Za-z]{2})\b')


def parse_address(raw_address: str) -> dict:
    """Parse a freeform Dutch address into components."""
    result = {"raw": raw_address, "street": "", "postcode": "", "city": ""}

    if not raw_address or raw_address.strip().lower() in ("ophalen", ""):
        return result

    addr = raw_address.strip()

    # Extract postcode
    pc_match = POSTCODE_RE.search(addr)
    if pc_match:
        result["postcode"] = pc_match.group(1) + pc_match.group(2).upper()

    # Extract city (check longest names first to match "Den Haag" before "Haag", etc.)
    addr_lower = addr.lower()
    for city in sorted(KNOWN_CITIES, key=len, reverse=True):
        if city.lower() in addr_lower:
            result["city"] = city
            break

    # If no city found, try the last part after the last comma
    if not result["city"]:
        parts = addr.split(",")
        if len(parts) >= 2:
            last_part = parts[-1].strip()
            # Remove postcode from the last part to get city name
            city_candidate = POSTCODE_RE.sub("", last_part).strip()
            if city_candidate:
                result["city"] = city_candidate

    # Street is everything before the postcode or city
    street = addr
    if pc_match:
        street = addr[:pc_match.start()].rstrip(", ")
    elif result["city"]:
        # Remove city from end
        idx = addr_lower.rfind(result["city"].lower())
        if idx > 0:
            street = addr[:idx].rstrip(", ")

    result["street"] = street

    return result


# ── Geocoding ──────────────────────────────────────────────────────────────

# City center fallback coordinates
CITY_CENTERS = {
    "Den Haag": (52.0705, 4.3007),
    "Rotterdam": (51.9225, 4.4792),
    "Utrecht": (52.0907, 5.1214),
    "Amsterdam": (52.3676, 4.9041),
    "Delft": (52.0116, 4.3571),
    "Katwijk": (52.1990, 4.4050),
    "Leiden": (52.1601, 4.4970),
    "Gouda": (52.0115, 4.7106),
    "Haarlem": (52.3812, 4.6360),
    "Hilversum": (52.2292, 5.1764),
    "Dordrecht": (51.8133, 4.6901),
    "Zoetermeer": (52.0600, 4.4950),
    "Almere": (52.3508, 5.2647),
    "Amersfoort": (52.1561, 5.3878),
    "Rijswijk": (52.0362, 4.3267),
    "Voorburg": (52.0700, 4.3600),
    "Wassenaar": (52.1452, 4.3993),
    "Wateringen": (52.0411, 4.2817),
    "Nootdorp": (52.0442, 4.3914),
    "Leidschendam": (52.0864, 4.3839),
    "Badhoevedorp": (52.3364, 4.7839),
    "Santpoort Zuid": (52.4100, 4.6200),
    "Schiedam": (51.9192, 4.3989),
}

_geocode_cache = {}


def geocode_address(address: str, geolocator: Nominatim) -> tuple[float, float] | None:
    """Geocode an address to (latitude, longitude). Uses caching and retries."""
    if address in _geocode_cache:
        return _geocode_cache[address]

    for attempt in range(3):
        try:
            location = geolocator.geocode(address, timeout=10)
            if location:
                coords = (location.latitude, location.longitude)
                _geocode_cache[address] = coords
                return coords
            break
        except Exception:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    return None


def geocode_order(parsed: dict, geolocator: Nominatim) -> tuple[float, float]:
    """Geocode a parsed address, using Nominatim with city-center fallback."""
    # Build a full address string for Nominatim
    parts = []
    if parsed["street"]:
        parts.append(parsed["street"])
    if parsed["postcode"]:
        parts.append(parsed["postcode"])
    if parsed["city"]:
        parts.append(parsed["city"])
    parts.append("Netherlands")

    full_address = ", ".join(parts)
    coords = geocode_address(full_address, geolocator)
    if coords:
        return coords

    # Fallback: try with just postcode + city
    if parsed["postcode"] and parsed["city"]:
        fallback = f"{parsed['postcode']} {parsed['city']}, Netherlands"
        coords = geocode_address(fallback, geolocator)
        if coords:
            return coords

    # Fallback: city center
    if parsed["city"] in CITY_CENTERS:
        return CITY_CENTERS[parsed["city"]]

    # Last resort: Den Haag center
    return CITY_CENTERS["Den Haag"]


def geocode_all_orders(orders: pd.DataFrame, geolocator: Nominatim) -> pd.DataFrame:
    """Geocode all order addresses."""
    lats, lons = [], []

    for _, row in orders.iterrows():
        coords = geocode_order(row["_parsed"], geolocator)
        lats.append(coords[0])
        lons.append(coords[1])
        print(f"  {row['Klant']:40s} -> ({coords[0]:.4f}, {coords[1]:.4f})  [{row['_city']}]")
        time.sleep(1.1)  # Respect Nominatim rate limit

    orders = orders.copy()
    orders["lat"] = lats
    orders["lon"] = lons
    return orders


# ── Car Assignment ─────────────────────────────────────────────────────────

def assign_car(city: str) -> str | None:
    """Assign an order to a car based on its city."""
    for car_name, cities in CAR_ASSIGNMENTS.items():
        if city in cities:
            return car_name
    return None


def assign_orders_to_cars(orders: pd.DataFrame, depot_coords: tuple) -> dict[str, pd.DataFrame]:
    """Assign each order to one of the 3 cars."""
    assignments = {car: [] for car in CAR_ASSIGNMENTS}

    car_centers = {
        "Car 1 - Den Haag": (52.0705, 4.3007),
        "Car 2 - Rotterdam & Utrecht": (51.98, 4.75),
        "Car 3 - Amsterdam": (52.3676, 4.9041),
    }

    for idx, row in orders.iterrows():
        car = assign_car(row["_city"])
        if car is None:
            # Find nearest car region by distance
            order_coords = (row["lat"], row["lon"])
            min_dist = float("inf")
            best_car = list(CAR_ASSIGNMENTS.keys())[0]
            for car_name, center in car_centers.items():
                dist = geodesic(order_coords, center).km
                if dist < min_dist:
                    min_dist = dist
                    best_car = car_name
            car = best_car
            print(f"  Assigned {row['_city'] or 'unknown'} ({row['Klant']}) -> {car} (nearest region)")
        assignments[car].append(idx)

    result = {}
    for car, indices in assignments.items():
        if indices:
            result[car] = orders.loc[indices].reset_index(drop=True)
    return result


# ── Distance Matrix ────────────────────────────────────────────────────────

def compute_distance_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
    """Compute distance matrix in km between all coordinate pairs."""
    n = len(coords)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            dist = geodesic(coords[i], coords[j]).km
            matrix[i][j] = dist
            matrix[j][i] = dist
    return matrix


def compute_time_matrix(distance_matrix: list[list[float]], speed_kmh: float) -> list[list[int]]:
    """Convert distance matrix to time matrix in seconds."""
    n = len(distance_matrix)
    time_matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                time_matrix[i][j] = int((distance_matrix[i][j] / speed_kmh) * 3600)
    return time_matrix


# ── TSP Route Optimization ────────────────────────────────────────────────

def solve_tsp(time_matrix: list[list[int]]) -> list[int] | None:
    """Solve TSP using Google OR-Tools. Node 0 is the depot."""
    n = len(time_matrix)
    if n <= 1:
        return [0]
    if n == 2:
        return [0, 1]

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return time_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.FromSeconds(5)

    solution = routing.SolveWithParameters(search_parameters)

    if solution:
        route = []
        index = routing.Start(0)
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        return route
    return None


# ── Route CSV Generation ──────────────────────────────────────────────────

def generate_route_csv(
    car_name: str,
    car_orders: pd.DataFrame,
    depot_coords: tuple,
    start_time: datetime,
    dropoff_minutes: int,
    output_dir: str,
    distance_matrix: list[list[float]],
    route_order: list[int],
) -> str:
    """Generate a CSV file with the delivery route for a car."""

    rows = []
    current_time = start_time
    dropoff_delta = timedelta(minutes=dropoff_minutes)

    for i in range(1, len(route_order)):
        prev_idx = route_order[i - 1]
        curr_idx = route_order[i]

        if prev_idx == 0:
            start_address = DEPOT_LABEL
        else:
            prev_order = car_orders.iloc[prev_idx - 1]
            start_address = prev_order["_address_raw"]

        order = car_orders.iloc[curr_idx - 1]
        delivery_address = order["_address_raw"]

        drive_seconds = int((distance_matrix[prev_idx][curr_idx] / AVG_SPEED_KMH) * 3600)
        drive_delta = timedelta(seconds=drive_seconds)

        depart_time = current_time
        arrive_time = depart_time + drive_delta
        dropoff_end = arrive_time + dropoff_delta

        rows.append({
            "Startadres": start_address,
            "Vertrektijd": depart_time.strftime("%H:%M"),
            "Bezorgadres": delivery_address,
            "Aankomsttijd": arrive_time.strftime("%H:%M"),
            "Aflevermoment": dropoff_end.strftime("%H:%M"),
            "Klant": order["Klant"],
            "Bestelling": order["Bestelling"],
            "Aantal": order["Q"],
        })

        current_time = dropoff_end

    df = pd.DataFrame(rows)
    safe_name = car_name.replace(" ", "_").replace("&", "en")
    filepath = os.path.join(output_dir, f"route_{safe_name}.csv")
    df.to_csv(filepath, index=False, sep=";")

    if rows:
        last_dropoff = rows[-1]["Aflevermoment"]
        total_dist = sum(
            distance_matrix[route_order[i - 1]][route_order[i]]
            for i in range(1, len(route_order))
        )
        print(f"  {car_name}: {len(rows)} stops, ~{total_dist:.1f} km, "
              f"done by {last_dropoff}")

    return filepath


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sushi Delivery Route Optimizer")
    parser.add_argument("--input", default="Overzicht bestellingen.xlsx",
                        help="Path to Excel file with orders")
    parser.add_argument("--start-time", default="12:00",
                        help="Start driving time HH:MM (default: 12:00)")
    parser.add_argument("--dropoff-time", type=int, default=5,
                        help="Minutes per delivery dropoff (default: 5)")
    parser.add_argument("--output-dir", default="./output",
                        help="Output directory for CSV files (default: ./output)")
    args = parser.parse_args()

    try:
        start_dt = datetime.strptime(args.start_time, "%H:%M")
        start_dt = start_dt.replace(year=2026, month=3, day=6)
    except ValueError:
        print(f"Error: Invalid time format '{args.start_time}'. Use HH:MM.")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Step 1: Read and filter Excel ──────────────────────────────────
    print("Step 1: Reading Excel file...")
    df = pd.read_excel(args.input)

    # Rename columns to internal names
    col_map = {
        "Q": "Q",
        "Bestelling": "Bestelling",
        "Klant": "Klant",
        "Ophalen/Bezorgen": "Type",
        "Adres (indien bezorgen)": "Adres_raw",
    }
    df = df.rename(columns=col_map)
    print(f"  Total rows: {len(df)}")

    # Filter for deliveries only (case-insensitive "leveren")
    df["Type_lower"] = df["Type"].astype(str).str.strip().str.lower()
    df_leveren = df[df["Type_lower"].str.contains("leveren", na=False)].copy()
    # Exclude pickup addresses
    df_leveren = df_leveren[
        ~df_leveren["Adres_raw"].astype(str).str.strip().str.lower().isin(["ophalen", ""])
    ].reset_index(drop=True)
    print(f"  Delivery orders: {len(df_leveren)}")

    if df_leveren.empty:
        print("No delivery orders found. Exiting.")
        sys.exit(0)

    # ── Step 2: Parse addresses ────────────────────────────────────────
    print("\nStep 2: Parsing addresses...")
    parsed_list = []
    cities = []
    for _, row in df_leveren.iterrows():
        parsed = parse_address(str(row["Adres_raw"]))
        parsed_list.append(parsed)
        cities.append(parsed["city"])

    df_leveren["_parsed"] = parsed_list
    df_leveren["_city"] = cities
    df_leveren["_address_raw"] = df_leveren["Adres_raw"].astype(str).str.strip()

    # Show parsed summary
    city_counts = df_leveren["_city"].value_counts()
    for city, count in city_counts.items():
        print(f"  {city or 'Unknown'}: {count} orders")

    # ── Step 3: Geocode addresses ──────────────────────────────────────
    print("\nStep 3: Geocoding addresses...")
    geolocator = Nominatim(user_agent="sushi_route_optimizer_v1")

    depot_coords = geocode_address(DEPOT_ADDRESS, geolocator)
    if depot_coords is None:
        print("  Could not geocode depot. Using known coordinates.")
        depot_coords = (52.0698, 4.3151)
    print(f"  Depot: {DEPOT_LABEL} -> {depot_coords}")

    df_leveren = geocode_all_orders(df_leveren, geolocator)
    print(f"  Geocoded {len(df_leveren)} addresses")

    # ── Step 4: Assign orders to cars ──────────────────────────────────
    print("\nStep 4: Assigning orders to cars...")
    car_groups = assign_orders_to_cars(df_leveren, depot_coords)

    for car, orders in car_groups.items():
        print(f"  {car}: {len(orders)} deliveries")

    # ── Step 5: Optimize routes per car ────────────────────────────────
    print("\nStep 5: Optimizing delivery routes...")
    output_files = []

    for car_name, car_orders in car_groups.items():
        print(f"\n  Optimizing {car_name}...")

        coords = [depot_coords]
        for _, row in car_orders.iterrows():
            coords.append((row["lat"], row["lon"]))

        dist_matrix = compute_distance_matrix(coords)
        time_matrix = compute_time_matrix(dist_matrix, AVG_SPEED_KMH)

        route = solve_tsp(time_matrix)
        if route is None:
            print(f"  WARNING: Could not optimize route for {car_name}. Using order as-is.")
            route = list(range(len(coords)))

        filepath = generate_route_csv(
            car_name=car_name,
            car_orders=car_orders,
            depot_coords=depot_coords,
            start_time=start_dt,
            dropoff_minutes=args.dropoff_time,
            output_dir=args.output_dir,
            distance_matrix=dist_matrix,
            route_order=route,
        )
        output_files.append(filepath)

    # ── Done ───────────────────────────────────────────────────────────
    print(f"\nDone! Route CSVs written to: {args.output_dir}/")
    for f in output_files:
        print(f"  {f}")


if __name__ == "__main__":
    main()
