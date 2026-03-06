# Rt123-sushi-routemapping

Sushi delivery route optimizer for Leger des Heils. Reads delivery orders from an Excel file, filters for orders tagged "Leveren", and generates optimized delivery routes for 3 cars.

## Quick Start

```bash
pip install openpyxl geopy ortools pandas
python optimize_routes.py --input "Overzicht bestellingen.xlsx" --start-time 12:00 --dropoff-time 5
```

### Arguments

| Argument | Default | Description |
|---|---|---|
| `--input` | `Overzicht bestellingen.xlsx` | Path to the Excel file with delivery orders |
| `--start-time` | `12:00` | Start driving time in HH:MM format |
| `--dropoff-time` | `5` | Minutes per delivery stop (parking + door delivery) |
| `--output-dir` | `./output` | Directory for the 3 output CSV files |

### Output

Three CSV files (semicolon-separated) are generated in the output directory, one per car:

- `route_Car_1_-_Den_Haag.csv` — Den Haag and nearby cities
- `route_Car_2_-_Rotterdam_en_Utrecht.csv` — Rotterdam, Utrecht, and surrounding areas
- `route_Car_3_-_Amsterdam.csv` — Amsterdam and surrounding areas

Each CSV contains: Startadres, Vertrektijd, Bezorgadres, Aankomsttijd, Aflevermoment, Klant, Bestelling, Aantal.

## How the Optimal Route Was Determined

### 1. Data Filtering

Only orders with the tag **"Leveren"** are included. Orders tagged "Afhalen" (pickup) are excluded since they don't require delivery.

### 2. Geocoding

Addresses are converted to GPS coordinates (latitude/longitude) using a two-tier approach:

- **Primary**: OpenStreetMap Nominatim geocoder — parses freeform addresses and geocodes them.
- **Fallback**: City-center coordinates for known Dutch cities when Nominatim cannot resolve the address.

### 3. Car Assignment

Orders are assigned to one of three cars based on city:

| Car | Primary Cities | Nearby Cities |
|---|---|---|
| Car 1 | Den Haag | Delft, Zoetermeer, Katwijk, Leiden, Rijswijk, Voorburg, Wassenaar, Wateringen, Nootdorp |
| Car 2 | Rotterdam, Utrecht | Gouda, Dordrecht, Amersfoort, Badhoevedorp |
| Car 3 | Amsterdam | Haarlem, Hilversum, Almere |

Orders from cities not in this list are assigned to the car whose region center is geographically closest (geodesic distance).

### 4. Route Optimization (TSP)

Each car's route is optimized independently using the **Travelling Salesman Problem (TSP)** formulation, solved with [Google OR-Tools](https://developers.google.com/optimization):

1. **Distance matrix**: Geodesic (great-circle) distances are computed between all pairs of locations (depot + delivery stops).
2. **Time matrix**: Distances are converted to driving time using an average urban speed of **40 km/h**.
3. **TSP solver**: OR-Tools' constraint solver finds the shortest-time route visiting all stops exactly once, starting from the depot (Leger des Heils, Brinckhorstlaan, Den Haag).

The solver uses:
- **Initial heuristic**: `PATH_CHEAPEST_ARC` — greedily builds a route by always choosing the nearest unvisited stop.
- **Metaheuristic improvement**: `GUIDED_LOCAL_SEARCH` — iteratively improves the initial solution by exploring alternative orderings, penalizing frequently-used edges to escape local optima.
- **Time limit**: 5 seconds per car — sufficient for the problem size (~10 stops per car) to reach near-optimal solutions.

### 5. Time Calculations

For each stop in the optimized route:
- **Driving time** = geodesic distance / 40 km/h
- **Dropoff time** = configurable (default 5 minutes), covering parking and door delivery
- **Next departure** = arrival time + dropoff time

All cars depart simultaneously from the depot at the configured start time (default 12:00).

### Why This Approach Gives the Best Route

- **TSP is the right model**: Each car must visit all assigned stops exactly once from a single depot — this is the classic TSP.
- **OR-Tools is proven**: Google's OR-Tools is an industry-standard solver used in production logistics. The guided local search metaheuristic consistently finds near-optimal solutions for problems of this scale.
- **Geodesic distances**: Using great-circle distances gives a good approximation for route planning in the flat Netherlands. While actual road distances are longer, the relative ordering of stops remains accurate.
- **Regional car splitting**: Grouping nearby cities per car minimizes cross-region driving and ensures each car serves a compact geographic area.

## Project Files

| File | Description |
|---|---|
| `Overzicht bestellingen.xlsx` | Input Excel file with delivery orders |
| `optimize_routes.py` | Main route optimization script |
| `output/` | Generated CSV route files |
