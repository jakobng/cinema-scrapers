import json
import os

def identify_failures():
    file_path = 'london-cinema-scrapers/data/showtimes.json'
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    failures = {} # Title -> {cinema, year, runtime}

    for entry in data:
        title = entry.get('movie_title', '').strip()
        if not title:
            continue
            
        if not entry.get('tmdb_id'):
            if title not in failures:
                failures[title] = []
            
            # Store context to see where it comes from
            failures[title].append({
                'cinema': entry.get('cinema_name'),
                'year': entry.get('year'),
                'runtime': entry.get('runtime') or entry.get('runtime_min')
            })

    print(f"Total Unique Failing Titles: {len(failures)}")
    print("-" * 50)
    
    # Sort by number of occurrences (maybe more popular failures are more important)
    sorted_failures = sorted(failures.items(), key=lambda x: len(x[1]), reverse=True)

    for title, contexts in sorted_failures:
        print(f"Title: '{title}'")
        # Print a few unique contexts
        unique_contexts = {}
        for c in contexts:
            key = f"{c['cinema']} | Yr:{c['year']} | Run:{c['runtime']}"
            unique_contexts[key] = unique_contexts.get(key, 0) + 1
        
        for ctx_str, count in list(unique_contexts.items())[:3]:
            print(f"   - {ctx_str} (x{count})")
        print("")

if __name__ == "__main__":
    identify_failures()
