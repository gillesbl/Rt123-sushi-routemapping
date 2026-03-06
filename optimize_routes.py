#!/usr/bin/env python3
"""
Sushi Delivery Route Optimizer

Reads an Excel file with delivery orders, filters for 'Leveren' tag,
assigns orders to 3 delivery cars (Den Haag, Rotterdam+Utrecht, Amsterdam),
and optimizes each car's route using TSP (Travelling Salesman Problem).

Usage:
    python optimize_routes.py --input bestellingen.xlsx --start-time 12:00 --dropoff-time 5

Args:
    --input:        Path to Excel file with delivery orders
    --start-time:   Start driving time in HH:MM format (default: 12:00)
    --dropoff-time:  Minutes per dropoff/delivery (default: 5)
    --output-dir:   Directory for output CSV files (default: ./output)
"""

import argparse
import math
import os
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
    "Car 1 - Den Haag": ["Den Haag", "Delft", "Zoetermeer", "Katwijk", "Leiden"],
    "Car 2 - Rotterdam & Utrecht": ["Rotterdam", "Utrecht", "Gouda", "Dordrecht", "Amersfoort"],
    "Car 3 - Amsterdam": ["Amsterdam", "Haarlem", "Hilversum", "Almere"],
}

# Average driving speed in km/h (urban delivery driving)
AVG_SPEED_KMH = 40

# ── Geocoding ──────────────────────────────────────────────────────────────

# Postcode-prefix to approximate coordinates lookup.
# Dutch postcodes: first 4 digits give a good area approximation.
# These are representative coordinates for postcode areas used in our data.
POSTCODE_COORDS = {
    # Den Haag area
    "2511": (52.0775, 4.3125),  # Centrum
    "2514": (52.0830, 4.3140),  # Noordeinde
    "2571": (52.0640, 4.2900),  # Loosduinen
    "2582": (52.0900, 4.2800),  # Statenkwartier
    "2518": (52.0810, 4.3240),  # Willemspark
    "2563": (52.0730, 4.2650),  # Laan van Meerdervoort west
    "2526": (52.0550, 4.3200),  # Laak
    # Rotterdam area
    "3012": (51.9180, 4.4760),  # Centrum-West
    "3014": (51.9170, 4.4580),  # Nieuwe Binnenweg
    "3011": (51.9225, 4.4792),  # Centrum
    "3025": (51.9100, 4.4400),  # Schiedam-grens
    # Utrecht area
    "3511": (52.0907, 5.1214),  # Centrum
    "3512": (52.0930, 5.1180),  # Voorstraat
    "3581": (52.0870, 5.1300),  # Nachtegaal
    "3513": (52.1000, 5.1150),  # Noord
    "3572": (52.0920, 5.1350),  # Biltstraat
    # Amsterdam area
    "1017": (52.3630, 4.8950),  # Centrum-Oost
    "1053": (52.3680, 4.8650),  # Kinkerbuurt
    "1073": (52.3550, 4.8930),  # De Pijp
    "1072": (52.3530, 4.8900),  # De Pijp-Zuid
    "1077": (52.3480, 4.8780),  # Zuid
    "1054": (52.3690, 4.8700),  # Overtoom
    # Surrounding areas
    "2611": (52.0116, 4.3571),  # Delft
    "2225": (52.1990, 4.4050),  # Katwijk
    "2311": (52.1601, 4.4970),  # Leiden
    "2801": (52.0115, 4.7106),  # Gouda
    "2011": (52.3812, 4.6360),  # Haarlem
    "1211": (52.2292, 5.1764),  # Hilversum
    "3311": (51.8133, 4.6901),  # Dordrecht
    "2711": (52.0600, 4.4950),  # Zoetermeer
    "1315": (52.3508, 5.2647),  # Almere
    "3811": (52.1561, 5.3878),  # Amersfoort
}

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


def geocode_by_postcode(postcode: str, city: str) -> tuple[float, float]:
    """Look up coordinates by postcode prefix, falling back to city center."""
    prefix = postcode.strip().replace(" ", "")[:4]
    if prefix in POSTCODE_COORDS:
        return POSTCODE_COORDS[prefix]
    if city in CITY_CENTERS:
        return CITY_CENTERS[city]
    return CITY_CENTERS["Den Haag"]


def geocode_all_orders(orders: pd.DataFrame, geolocator: Nominatim) -> pd.DataFrame:
    """Geocode all order addresses using postcode lookup with Nominatim fallback."""
    lats, lons = [], []

    for _, row in orders.iterrows():
        # Primary: postcode-based lookup (fast, no API calls)
        coords = geocode_by_postcode(row["Postcode"], row["Stad"])

        # Try Nominatim for better accuracy (with rate limiting)
        full_address = f"{row['Adres']}, {row['Postcode']} {row['Stad']}, Netherlands"
        nominatim_coords = geocode_address(full_address, geolocator)
        if nominatim_coords:
            coords = nominatim_coords
        else:
            time.sleep(1.1)  # Respect Nominatim rate limit

        lats.append(coords[0])
        lons.append(coords[1])
        print(f"  {row['Klant']:30s} -> ({coords[0]:.4f}, {coords[1]:.4f})")

    orders = orders.copy()
    orders["lat"] = lats
    orders["lon"] = lons
    return orders


# ── Car Assignment ─────────────────────────────────────────────────────────

def assign_car(city: str) -> str:
    """Assign an order to a car based on its city."""
    for car_name, cities in CAR_ASSIGNMENTS.items():
        if city in cities:
            return car_name
    # For unknown cities, find closest car region center
    return None


def assign_orders_to_cars(orders: pd.DataFrame, depot_coords: tuple) -> dict[str, pd.DataFrame]:
    """Assign each order to one of the 3 cars."""
    assignments = {car: [] for car in CAR_ASSIGNMENTS}

    # Pre-compute approximate centers for each car region
    car_centers = {
        "Car 1 - Den Haag": (52.0705, 4.3007),       # Den Haag
        "Car 2 - Rotterdam & Utrecht": (51.98, 4.75),  # Between R'dam and Utrecht
        "Car 3 - Amsterdam": (52.3676, 4.9041),        # Amsterdam
    }

    for idx, row in orders.iterrows():
        car = assign_car(row["Stad"])
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
            print(f"  Assigned {row['Stad']} ({row['Klant']}) -> {car} (nearest region)")
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
                # Time in seconds = (distance_km / speed_kmh) * 3600
                time_matrix[i][j] = int((distance_matrix[i][j] / speed_kmh) * 3600)
    return time_matrix


# ── TSP Route Optimization ────────────────────────────────────────────────

def solve_tsp(time_matrix: list[list[int]]) -> list[int] | None:
    """
    Solve TSP using Google OR-Tools.
    Node 0 is the depot. Returns ordered list of node indices.
    """
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

    # Set search parameters
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

    # Build coordinate list (depot=0, then orders)
    # route_order[0] = 0 (depot), route_order[1:] = delivery stops

    for i in range(1, len(route_order)):
        prev_idx = route_order[i - 1]
        curr_idx = route_order[i]

        # Previous location
        if prev_idx == 0:
            start_address = DEPOT_LABEL
        else:
            prev_order = car_orders.iloc[prev_idx - 1]
            start_address = f"{prev_order['Adres']}, {prev_order['Stad']}"

        # Current delivery
        order = car_orders.iloc[curr_idx - 1]
        delivery_address = f"{order['Adres']}, {order['Postcode']} {order['Stad']}"

        # Driving time
        drive_seconds = int((distance_matrix[prev_idx][curr_idx] / AVG_SPEED_KMH) * 3600)
        drive_delta = timedelta(seconds=drive_seconds)

        # Times
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
        })

        current_time = dropoff_end

    df = pd.DataFrame(rows)
    safe_name = car_name.replace(" ", "_").replace("&", "en")
    filepath = os.path.join(output_dir, f"route_{safe_name}.csv")
    df.to_csv(filepath, index=False, sep=";")

    # Summary
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
    parser.add_argument("--input", required=True, help="Path to Excel file with orders")
    parser.add_argument("--start-time", default="12:00",
                        help="Start driving time HH:MM (default: 12:00)")
    parser.add_argument("--dropoff-time", type=int, default=5,
                        help="Minutes per delivery dropoff (default: 5)")
    parser.add_argument("--output-dir", default="./output",
                        help="Output directory for CSV files (default: ./output)")
    args = parser.parse_args()

    # Parse start time
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
    print(f"  Total orders: {len(df)}")

    # Filter for 'Leveren' only
    df_leveren = df[df["Tag"] == "Leveren"].reset_index(drop=True)
    print(f"  Orders with 'Leveren' tag: {len(df_leveren)}")

    if df_leveren.empty:
        print("No 'Leveren' orders found. Exiting.")
        sys.exit(0)

    # ── Step 2: Geocode addresses ──────────────────────────────────────
    print("\nStep 2: Geocoding addresses...")
    geolocator = Nominatim(user_agent="sushi_route_optimizer_v1")

    # Geocode depot
    depot_coords = geocode_address(DEPOT_ADDRESS, geolocator)
    if depot_coords is None:
        print("  Could not geocode depot. Using known coordinates.")
        depot_coords = (52.0698, 4.3151)  # Brinckhorstlaan, Den Haag
    print(f"  Depot: {DEPOT_LABEL} -> {depot_coords}")

    # Geocode all orders
    df_leveren = geocode_all_orders(df_leveren, geolocator)
    print(f"  Geocoded {len(df_leveren)} addresses")

    # ── Step 3: Assign orders to cars ──────────────────────────────────
    print("\nStep 3: Assigning orders to cars...")
    car_groups = assign_orders_to_cars(df_leveren, depot_coords)

    for car, orders in car_groups.items():
        print(f"  {car}: {len(orders)} deliveries")

    # ── Step 4: Optimize routes per car ────────────────────────────────
    print("\nStep 4: Optimizing delivery routes...")
    output_files = []

    for car_name, car_orders in car_groups.items():
        print(f"\n  Optimizing {car_name}...")

        # Build coordinate list: depot (index 0) + order locations
        coords = [depot_coords]
        for _, row in car_orders.iterrows():
            coords.append((row["lat"], row["lon"]))

        # Compute distance and time matrices
        dist_matrix = compute_distance_matrix(coords)
        time_matrix = compute_time_matrix(dist_matrix, AVG_SPEED_KMH)

        # Solve TSP
        route = solve_tsp(time_matrix)
        if route is None:
            print(f"  WARNING: Could not optimize route for {car_name}. Using order as-is.")
            route = list(range(len(coords)))

        # Generate CSV
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
