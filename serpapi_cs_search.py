import os
import json
import csv
import serpapi

# Set your SerpApi key as env var: export SERPAPI_KEY="your_key_here"
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "cc4034242f0f1ee963aecee7cc6d7c470ae5d596b697f78dd89cbe1b56b39879")

companies = [
    "Exotel",
    "WebEngage",
    "Vymo",
    "Signzy",
    "HyperVerge",
    "Decentro",
    "Netradyne",
    "Unilog",
    "Unbox Robotics",
    "Qoruz",
    "Appsmith",
    "Hasura",
    "SpotDraft",
    "Zluri",
    "Sprinto",
    "Scrut Automation",
    "CloudSEK",
    "Locus",
    "Freightify",
    "Unifize",
    "Clueso",
    "Skit.ai",
    "Gnani.ai",
    "Verloop.io",
    "Spyne",
    "Plum",
    "Onsurity",
    "Open Financial Technologies",
    "Tookitaki",
    "Innoviti",
    "Tracxn",
    "Facets.cloud",
    "eshopbox",
    "Infosec Ventures",
    "Shipsy",
    "Zippee",
    "Trademo",
    "Droom Enterprise",
    "eshopbox Logistics",
    "Increff",
    "Fleetx",
    "SuperOps",
    "ClickPost",
    "Advantage Club",
]

titles = [
    "Head of Customer Success",
    "VP Customer Success",
    "Chief Customer Officer",
    "Director of Customer Success",
    "Head of Client Success",
    "VP Client Success",
    "Customer Success",
    "Client Success",
]

def build_query(company: str) -> str:
    titles_part = " OR ".join(f'"{t}"' for t in titles)
    query = f'site:linkedin.com/in ({titles_part}) "{company}" 2026 -ex "{company}" -"former" "{company}" -"previously" "{company}"'
    return query

def search_company(company: str, serpapi_key: str, num_results: int = 5):
    q = build_query(company)
    
    # SerpApi 1.x usage
    client = serpapi.Client(api_key=serpapi_key)
    
    try:
        # Google Search
        results = client.search(
            engine="google",
            q=q,
            num=num_results,
            gl="in",
            hl="en",
        )
        
        organic = results.get("organic_results", [])
        rows = []
        for r in organic[:num_results]:
            title = r.get("title", "")
            link = r.get("link", "")
            snippet = r.get("snippet", "")
            
            # Simple extraction: name is usually first token before "|" or " - "
            name = title.split("|")[0].split(" - ")[0].strip()
            
            # Designation: try to pick one of the titles from snippet or title
            designation = None
            for t in titles:
                if t.lower() in title.lower():
                    designation = t
                    break
            if not designation:
                for t in titles:
                    if t.lower() in snippet.lower():
                        designation = t
                        break
            if not designation:
                # Fallback: use headline-like text from snippet before company name
                designation = snippet.split(company)[0].strip() if company in snippet else ""
            
            rows.append({
                "company": company,
                "name": name,
                "designation": designation,
                "title": title,
                "linkedin_url": link,
                "snippet": snippet,
            })
        return rows
    except Exception as e:
        print(f"Error for {company}: {e}")
        return []

def run_all_companies(output_csv: str = "cs_leads.csv"):
    all_rows = []
    for company in companies:
        print(f"Searching: {company}")
        rows = search_company(company, SERPAPI_KEY, num_results=5)
        all_rows.extend(rows)
    
    # Save to CSV
    if not all_rows:
        print("No results found.")
        return
    
    fieldnames = ["company", "name", "designation", "title", "linkedin_url", "snippet"]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    
    print(f"Saved {len(all_rows)} rows to {output_csv}")

if __name__ == "__main__":
    # Test single company first
    # sample_company = "Vymo"
    # rows = search_company(sample_company, SERPAPI_KEY, num_results=5)
    # print(json.dumps(rows, indent=2, ensure_ascii=False))
    
    # Run for all companies
    run_all_companies("cs_leads.csv")