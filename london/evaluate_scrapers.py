import json
import os

def evaluate_scrapers():
    file_path = 'london-cinema-scrapers/data/showtimes.json'
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Error decoding JSON")
            return

    total_showtimes = len(data)
    unique_movies = {}

    for entry in data:
        # distinct films by title (and optionally cinema if we consider 'film at a cinema' as the unit)
        # Using movie_title as the key for unique films across all cinemas
        title = entry.get('movie_title', '').strip()
        if not title:
            continue
            
        if title not in unique_movies:
            unique_movies[title] = {
                'count': 0,
                'has_tmdb': False,
                'has_genre': False,
                'has_runtime': False,
                'has_year': False
            }
        
        unique_movies[title]['count'] += 1
        
        # Check fields
        if entry.get('tmdb_id'):
            unique_movies[title]['has_tmdb'] = True
        
        genres = entry.get('genres')
        if genres and isinstance(genres, list) and len(genres) > 0:
            unique_movies[title]['has_genre'] = True
            
        runtime = entry.get('runtime') or entry.get('runtime_min')
        if runtime:
             unique_movies[title]['has_runtime'] = True

        year = entry.get('year')
        if year:
            unique_movies[title]['has_year'] = True

    total_unique = len(unique_movies)
    
    tmdb_count = sum(1 for m in unique_movies.values() if m['has_tmdb'])
    genre_count = sum(1 for m in unique_movies.values() if m['has_genre'])
    runtime_count = sum(1 for m in unique_movies.values() if m['has_runtime'])
    year_count = sum(1 for m in unique_movies.values() if m['has_year'])

    print(f"Total Showtimes: {total_showtimes}")
    print(f"Total Unique Films: {total_unique}")
    print("-" * 30)
    print(f"TMDB Link Success: {tmdb_count}/{total_unique} ({tmdb_count/total_unique*100:.1f}%)")
    print(f"Genre Found:       {genre_count}/{total_unique} ({genre_count/total_unique*100:.1f}%)")
    print(f"Runtime Found:     {runtime_count}/{total_unique} ({runtime_count/total_unique*100:.1f}%)")
    print(f"Year Found:        {year_count}/{total_unique} ({year_count/total_unique*100:.1f}%)")
    
    # Also Breakdown by Cinema (if useful, maybe later)

if __name__ == "__main__":
    evaluate_scrapers()
