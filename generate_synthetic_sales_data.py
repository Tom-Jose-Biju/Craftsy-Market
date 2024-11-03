import csv
import random
from datetime import datetime, timedelta

# List of sample product names and categories (using your existing data)
product_names = ["Handmade Necklace", "Artisan Mug", "Woven Basket", "Ceramic Vase", "Wooden Sculpture", 
                 "Embroidered Pillow", "Leather Wallet", "Painted Canvas", "Knitted Scarf", "Glass Ornament",
                 "Handwoven Rug", "Pottery Bowl", "Macrame Wall Hanging", "Carved Wooden Box", "Stained Glass Panel"]
categories = ["Jewelry", "Pottery", "Home Decor", "Textiles", "Accessories", "Art", "Furniture"]

# Generate synthetic data
def generate_data(num_artisans, num_days):
    data = []
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=num_days)

    for artisan_id in range(1, num_artisans + 1):
        num_products = random.randint(3, 8)  # Reduced number of products per artisan
        products = [(random.choice(product_names), random.choice(categories), random.uniform(10, 500)) for _ in range(num_products)]
        
        current_date = start_date
        while current_date <= end_date:
            for product_id, (product_name, category, base_price) in enumerate(products, 1):
                if random.random() < 0.2:  # 20% chance of a sale on any given day
                    quantity = random.randint(1, 5)  # Reduced max quantity
                    price = round(base_price * random.uniform(0.95, 1.05), 2)  # Smaller price variation
                    data.append([
                        current_date.strftime("%Y-%m-%d"),
                        artisan_id,
                        product_id,
                        product_name,
                        category,
                        quantity,
                        price
                    ])
            current_date += timedelta(days=1)

    return data

# Generate data for 10 artisans over the last 90 days
synthetic_data = generate_data(10, 90)

# Ensure we have at least 250 entries
while len(synthetic_data) < 250:
    synthetic_data.extend(generate_data(2, 30))

# Shuffle the data to mix up the dates and artisans
random.shuffle(synthetic_data)

# Take the first 250 entries
synthetic_data = synthetic_data[:250]

# Sort the data by date
synthetic_data.sort(key=lambda x: x[0])

# Save data to CSV
csv_filename = "artisan_sales_data.csv"
with open(csv_filename, mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(["date", "artisan_id", "product_id", "product_name", "category", "quantity", "price"])
    writer.writerows(synthetic_data)

print(f"Synthetic data with 250 entries has been generated and saved to {csv_filename}")