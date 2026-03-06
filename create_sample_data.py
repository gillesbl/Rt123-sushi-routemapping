"""
Script to create sample Excel delivery data for sushi route mapping.
This generates a realistic dataset with Dutch addresses across Den Haag,
Rotterdam, Utrecht, Amsterdam and surrounding areas.
"""

import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Bestellingen"

headers = ["Bestelling", "Klant", "Adres", "Postcode", "Stad", "Tag"]
ws.append(headers)

# Delivery data - mix of Leveren and Afhalen tags
orders = [
    # Den Haag
    ("B001", "Tanaka Sushi Bar", "Grote Marktstraat 45", "2511 BH", "Den Haag", "Leveren"),
    ("B002", "De Japanse Keuken", "Noordeinde 12", "2514 GL", "Den Haag", "Leveren"),
    ("B003", "Sushi Express DH", "Loosduinsekade 145", "2571 AB", "Den Haag", "Leveren"),
    ("B004", "Restaurant Sakura", "Frederik Hendriklaan 80", "2582 BH", "Den Haag", "Leveren"),
    ("B005", "Asia Market DH", "Hobbemastraat 30", "2526 JJ", "Den Haag", "Afhalen"),
    ("B006", "Wasabi Den Haag", "Prins Hendrikstraat 10", "2518 HK", "Den Haag", "Leveren"),
    ("B007", "Konnichiwa DH", "Laan van Meerdervoort 250", "2563 AJ", "Den Haag", "Leveren"),

    # Rotterdam
    ("B008", "Sushi Time Rotterdam", "Witte de Withstraat 50", "3012 BR", "Rotterdam", "Leveren"),
    ("B009", "Oishi Rotterdam", "Nieuwe Binnenweg 75", "3014 GE", "Rotterdam", "Leveren"),
    ("B010", "Tokyo Ramen R'dam", "Coolsingel 100", "3011 AG", "Rotterdam", "Leveren"),
    ("B011", "Nippon Kitchen", "Meent 22", "3011 JN", "Rotterdam", "Afhalen"),
    ("B012", "Sushi Palace R'dam", "Karel Doormanstraat 300", "3012 GP", "Rotterdam", "Leveren"),
    ("B013", "Maki & More", "Schiedamseweg 60", "3025 AE", "Rotterdam", "Leveren"),

    # Utrecht
    ("B014", "Sushi & Co Utrecht", "Oudegracht 150", "3511 AZ", "Utrecht", "Leveren"),
    ("B015", "Sakana Utrecht", "Voorstraat 88", "3512 AT", "Utrecht", "Leveren"),
    ("B016", "Japanese Kitchen UU", "Nachtegaalstraat 30", "3581 AD", "Utrecht", "Leveren"),
    ("B017", "Tokyo Bowl Utrecht", "Amsterdamsestraatweg 200", "3513 AG", "Utrecht", "Afhalen"),
    ("B018", "Zen Sushi Utrecht", "Biltstraat 45", "3572 AD", "Utrecht", "Leveren"),

    # Amsterdam
    ("B019", "Sushi Amsterdam", "Reguliersdwarsstraat 40", "1017 BN", "Amsterdam", "Leveren"),
    ("B020", "Omakase Amsterdam", "Utrechtsestraat 75", "1017 VJ", "Amsterdam", "Leveren"),
    ("B021", "Izakaya A'dam", "Kinkerstraat 100", "1053 ED", "Amsterdam", "Leveren"),
    ("B022", "Moshi Moshi AMS", "Albert Cuypstraat 150", "1073 BL", "Amsterdam", "Leveren"),
    ("B023", "Sashimi Place", "Ferdinand Bolstraat 30", "1072 LJ", "Amsterdam", "Afhalen"),
    ("B024", "Tokyo Garden AMS", "Beethovenstraat 60", "1077 JJ", "Amsterdam", "Leveren"),
    ("B025", "Fuji Sushi A'dam", "Overtoom 200", "1054 HP", "Amsterdam", "Leveren"),

    # Surrounding areas (to test assignment logic)
    ("B026", "Sushi Delft", "Markt 20", "2611 GP", "Delft", "Leveren"),
    ("B027", "Japanese Corner", "Voorstraat 50", "2225 EN", "Katwijk", "Leveren"),
    ("B028", "Sushi Leiden", "Breestraat 100", "2311 CS", "Leiden", "Leveren"),
    ("B029", "Sushi Gouda", "Markt 35", "2801 JJ", "Gouda", "Leveren"),
    ("B030", "Edo Sushi Haarlem", "Grote Houtstraat 50", "2011 SG", "Haarlem", "Leveren"),
    ("B031", "Maki Hilversum", "Kerkstraat 60", "1211 CW", "Hilversum", "Leveren"),
    ("B032", "Sushi Dordrecht", "Voorstraat 200", "3311 ES", "Dordrecht", "Leveren"),
    ("B033", "Wasabi Zoetermeer", "Stadshart 100", "2711 EC", "Zoetermeer", "Leveren"),
    ("B034", "Tokyo Almere", "Stadhuisplein 1", "1315 HR", "Almere", "Leveren"),
    ("B035", "Sushi Amersfoort", "Langestraat 50", "3811 NJ", "Amersfoort", "Leveren"),
]

for order in orders:
    ws.append(order)

# Auto-adjust column widths
for col in ws.columns:
    max_length = max(len(str(cell.value or "")) for cell in col)
    ws.column_dimensions[col[0].column_letter].width = max_length + 2

wb.save("/home/user/Rt123-sushi-routemapping/bestellingen.xlsx")
print(f"Created bestellingen.xlsx with {len(orders)} orders")
print(f"Leveren orders: {sum(1 for o in orders if o[5] == 'Leveren')}")
print(f"Afhalen orders: {sum(1 for o in orders if o[5] == 'Afhalen')}")
