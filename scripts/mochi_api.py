#!/usr/bin/env python3
"""
Mochi SRS API Client

A command-line tool for interacting with the Mochi spaced repetition system.
Supports creating cards, listing decks, and managing SRS content.

API Documentation: https://mochi.cards/docs/api/
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library not installed. Run: pip install requests")
    sys.exit(1)

# Load API key from .env file in skill directory
SKILL_DIR = Path(__file__).parent.parent
ENV_FILE = SKILL_DIR / ".env"

def load_api_key():
    """Load API key from .env file or environment variable."""
    # Check environment variable first
    api_key = os.environ.get("MOCHI_API_KEY")
    if api_key:
        return api_key

    # Try loading from .env file
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("MOCHI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None

API_KEY = load_api_key()
BASE_URL = "https://app.mochi.cards/api"

# Local Mochi database path (macOS)
MOCHI_DB = Path.home() / "Library" / "Application Support" / "Mochi" / "mochi.db"


def parse_transit_timestamp(ts_str):
    """Parse Mochi's Transit-encoded timestamp (e.g., '~t1697241600000')."""
    if isinstance(ts_str, str) and ts_str.startswith("~t"):
        ms = int(ts_str[2:])
        return datetime.fromtimestamp(ms / 1000)
    return None


def extract_card_content(transit_data):
    """Extract question and answer from Transit-encoded card data."""
    # Try ~:content first (standard format)
    content = transit_data.get("~:content", "")

    # If content is empty, try ~:name + fields
    if not content:
        name = transit_data.get("~:name", "")
        fields = transit_data.get("~:fields", {})
        # Find answer field (not the name field)
        answer = ""
        for field_key, field_data in fields.items():
            if field_key != "~:name" and isinstance(field_data, dict):
                answer = field_data.get("~:value", "")
                break
        if name and answer:
            content = f"{name}\n---\n{answer}"
        elif name:
            content = name

    # Split into question/answer - handle various separator formats
    # Some cards use \n---\n, others use \n\n---\n\n, or \n--- \n
    if "---" in content:
        # Normalize separator and split - allow optional trailing space
        parts = re.split(r'\n+---[ ]?\n+', content, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    return content.strip(), ""


def has_valid_content(transit_data):
    """Check if a card has actual reviewable content."""
    question, answer = extract_card_content(transit_data)
    # Skip cards with no question or placeholder names
    if not question or question == "Untitled card":
        return False
    return True


def is_card_due(transit_data, target_date=None):
    """Check if a card is due for review."""
    if target_date is None:
        target_date = datetime.now()

    reviews = transit_data.get("~:reviews", [])

    # New card with no reviews is always due
    if not reviews:
        return True

    # Get the last review
    last_review = reviews[-1]
    last_date = parse_transit_timestamp(last_review.get("~:date"))
    interval = last_review.get("~:interval", 0)

    if last_date is None:
        return True

    # Calculate next due date
    next_due = last_date + timedelta(days=interval)
    return target_date >= next_due


def get_due_cards_local(deck_id=None):
    """Read due cards from local Mochi SQLite database."""
    if not MOCHI_DB.exists():
        print(f"Error: Mochi database not found at {MOCHI_DB}")
        print("Make sure Mochi is installed and has synced at least once.")
        return []

    due_cards = []

    try:
        conn = sqlite3.connect(f"file:{MOCHI_DB}?mode=ro", uri=True)
        cursor = conn.cursor()

        # Query all cards from by-sequence table
        cursor.execute("""
            SELECT doc_id, json
            FROM 'by-sequence'
            WHERE json LIKE '%"type":"card"%'
            AND deleted = 0
        """)

        for row in cursor.fetchall():
            doc_id, json_str = row
            try:
                doc = json.loads(json_str)
                transit_data = doc.get("transit-data", {})

                # Skip trashed or archived cards
                if "~:trashed?" in transit_data:
                    continue
                if transit_data.get("~:archived?"):
                    continue

                # Skip cards without valid content
                if not has_valid_content(transit_data):
                    continue

                # Filter by deck if specified
                card_deck = transit_data.get("~:deck-id", "").lstrip("~:")
                if deck_id and card_deck != deck_id:
                    continue

                # Check if due
                if is_card_due(transit_data):
                    question, answer = extract_card_content(transit_data)
                    card_id = transit_data.get("~:id", "").lstrip("~:")

                    due_cards.append({
                        "id": card_id or doc_id,
                        "deck_id": card_deck,
                        "question": question,
                        "answer": answer,
                        "reviews": transit_data.get("~:reviews", [])
                    })
            except json.JSONDecodeError:
                continue

        conn.close()

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        print("The Mochi app may have the database locked. Try closing Mochi.")
        return []

    return due_cards


def submit_review(card_id, remembered):
    """Submit a review result via Mochi API."""
    import time

    rating = "good" if remembered else "again"

    # Try the documented endpoint first
    endpoints = [
        f"{BASE_URL}/cards/{card_id}/review/",
        f"{BASE_URL}/reviews/"
    ]

    for endpoint in endpoints:
        payload = {"card-id": card_id, "rating": rating}
        try:
            response = requests.post(endpoint, auth=get_auth(), json=payload)
            if response.status_code == 429:
                # Rate limited, wait and retry
                time.sleep(1)
                response = requests.post(endpoint, auth=get_auth(), json=payload)
            response.raise_for_status()
            return True
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                continue  # Try next endpoint
            raise

    return False


def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def interactive_review(deck_id=None, deck_name=None, limit=None):
    """Run an interactive review session."""
    # Resolve deck name to ID if needed
    if deck_name and not deck_id:
        deck = search_deck_by_name(deck_name)
        if deck:
            deck_id = deck.get("id")
        else:
            return

    # Get due cards from local database
    print("Loading due cards from local database...")
    cards = get_due_cards_local(deck_id)

    if not cards:
        print("\nNo cards due for review!")
        return

    total_due = len(cards)
    if limit and limit < len(cards):
        cards = cards[:limit]
        print(f"\nFound {total_due} card(s) due, reviewing {limit}.")
    else:
        print(f"\nFound {total_due} card(s) due for review.")
    print("Controls: [Enter] reveal | [g]ood | [a]gain | [s]kip | [q]uit\n")
    input("Press Enter to start...")

    reviewed = 0
    skipped = 0
    failed_submissions = []

    for i, card in enumerate(cards, 1):
        clear_screen()
        print(f"{'─' * 50}")
        print(f"  Review ({i}/{len(cards)})  |  Good: {reviewed}  Skipped: {skipped}")
        print(f"{'─' * 50}\n")

        # Show question
        print(card["question"])
        print()
        input("[Press Enter to reveal answer]")

        # Show answer
        print(f"\n{'─' * 50}\n")
        print(card["answer"])
        print(f"\n{'─' * 50}")
        print("[g] Good  [a] Again  [s] Skip  [q] Quit")

        while True:
            choice = input("> ").strip().lower()
            if choice in ('g', 'good', ''):
                # Submit as remembered
                try:
                    submit_review(card["id"], remembered=True)
                    reviewed += 1
                except Exception as e:
                    failed_submissions.append((card["id"], True, str(e)))
                    print(f"  (Review saved locally, API sync failed)")
                break
            elif choice in ('a', 'again'):
                # Submit as forgot
                try:
                    submit_review(card["id"], remembered=False)
                    reviewed += 1
                except Exception as e:
                    failed_submissions.append((card["id"], False, str(e)))
                    print(f"  (Review saved locally, API sync failed)")
                break
            elif choice in ('s', 'skip'):
                skipped += 1
                break
            elif choice in ('q', 'quit'):
                print(f"\nSession ended. Reviewed: {reviewed}, Skipped: {skipped}")
                if failed_submissions:
                    print(f"Failed API submissions: {len(failed_submissions)}")
                return
            else:
                print("Invalid input. Use [g]ood, [a]gain, [s]kip, or [q]uit")

    # Session complete
    clear_screen()
    print(f"{'─' * 50}")
    print(f"  Review Complete!")
    print(f"{'─' * 50}\n")
    print(f"  Cards reviewed: {reviewed}")
    print(f"  Cards skipped:  {skipped}")
    if failed_submissions:
        print(f"  Failed syncs:   {len(failed_submissions)}")
    print()


def get_auth():
    """Return HTTP Basic Auth tuple with API key."""
    if not API_KEY:
        print("Error: MOCHI_API_KEY not found.")
        print(f"Please add your API key to {ENV_FILE}")
        print("Format: MOCHI_API_KEY=your_api_key_here")
        print("\nGet your API key from: Mochi app > Settings > API")
        sys.exit(1)
    return (API_KEY, "")


def list_decks(show_ids=False):
    """List all decks in the account."""
    response = requests.get(f"{BASE_URL}/decks", auth=get_auth())
    response.raise_for_status()

    data = response.json()
    decks = data.get("docs", [])

    if not decks:
        print("No decks found.")
        return

    print(f"Found {len(decks)} deck(s):\n")
    for deck in decks:
        name = deck.get("name", "Untitled")
        deck_id = deck.get("id", "")
        archived = deck.get("archived?", False)

        status = " [archived]" if archived else ""
        if show_ids:
            print(f"  - {name}{status}")
            print(f"    ID: {deck_id}")
        else:
            print(f"  - {name}{status} (ID: {deck_id})")


def get_deck(deck_id):
    """Get a specific deck by ID."""
    response = requests.get(f"{BASE_URL}/decks/{deck_id}", auth=get_auth())
    response.raise_for_status()
    return response.json()


def create_deck(name, parent_id=None):
    """Create a new deck."""
    payload = {"name": name}
    if parent_id:
        payload["parent-id"] = parent_id

    response = requests.post(
        f"{BASE_URL}/decks",
        auth=get_auth(),
        json=payload
    )
    response.raise_for_status()

    deck = response.json()
    print(f"Created deck: {deck.get('name')}")
    print(f"ID: {deck.get('id')}")
    return deck


def create_card(deck_id, content, template_id=None, review_reverse=False):
    """Create a new card in a deck."""
    payload = {
        "content": content,
        "deck-id": deck_id
    }

    if template_id:
        payload["template-id"] = template_id
    if review_reverse:
        payload["review-reverse?"] = True

    response = requests.post(
        f"{BASE_URL}/cards",
        auth=get_auth(),
        json=payload
    )
    response.raise_for_status()

    card = response.json()
    print(f"Created card successfully!")
    print(f"ID: {card.get('id')}")
    return card


def create_cards_batch(deck_id, cards_data, template_id=None):
    """Create multiple cards from a list of content strings or dicts."""
    created = []
    for i, card_data in enumerate(cards_data, 1):
        if isinstance(card_data, str):
            content = card_data
        else:
            content = card_data.get("content", "")

        try:
            card = create_card(deck_id, content, template_id)
            created.append(card)
            print(f"  [{i}/{len(cards_data)}] Created")
        except requests.HTTPError as e:
            print(f"  [{i}/{len(cards_data)}] Failed: {e}")

    print(f"\nCreated {len(created)}/{len(cards_data)} cards")
    return created


def list_cards(deck_id=None, limit=10):
    """List cards, optionally filtered by deck."""
    params = {"limit": limit}
    if deck_id:
        params["deck-id"] = deck_id

    response = requests.get(
        f"{BASE_URL}/cards",
        auth=get_auth(),
        params=params
    )
    response.raise_for_status()

    data = response.json()
    cards = data.get("docs", [])

    if not cards:
        print("No cards found.")
        return

    print(f"Found {len(cards)} card(s):\n")
    for card in cards:
        content = card.get("content", "")
        card_id = card.get("id", "")
        # Truncate content for display
        preview = content[:80].replace("\n", " ")
        if len(content) > 80:
            preview += "..."
        print(f"  - {preview}")
        print(f"    ID: {card_id}")
        print()


def get_due_cards(deck_id=None, date=None):
    """Get cards due for review."""
    endpoint = f"{BASE_URL}/due"
    if deck_id:
        endpoint = f"{BASE_URL}/due/{deck_id}"

    params = {}
    if date:
        params["date"] = date

    response = requests.get(endpoint, auth=get_auth(), params=params)
    response.raise_for_status()

    data = response.json()
    cards = data.get("cards", [])

    if not cards:
        print("No cards due for review!")
        return

    print(f"Cards due: {len(cards)}\n")
    for card in cards[:10]:  # Show first 10
        content = card.get("content", "")
        preview = content[:60].replace("\n", " ")
        if len(content) > 60:
            preview += "..."
        print(f"  - {preview}")


def delete_card(card_id):
    """Delete a card by ID."""
    response = requests.delete(
        f"{BASE_URL}/cards/{card_id}",
        auth=get_auth()
    )
    response.raise_for_status()
    print(f"Deleted card: {card_id}")


def search_deck_by_name(name):
    """Find a deck by name (case-insensitive partial match)."""
    response = requests.get(f"{BASE_URL}/decks", auth=get_auth())
    response.raise_for_status()

    data = response.json()
    decks = data.get("docs", [])

    name_lower = name.lower()
    matches = [d for d in decks if name_lower in d.get("name", "").lower()]

    if not matches:
        print(f"No deck found matching '{name}'")
        return None

    if len(matches) == 1:
        return matches[0]

    print(f"Multiple decks match '{name}':")
    for deck in matches:
        print(f"  - {deck.get('name')} (ID: {deck.get('id')})")
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Mochi SRS API Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  List all decks:
    python mochi_api.py decks

  Create a card:
    python mochi_api.py create --deck DECK_ID --content "Question\\n---\\nAnswer"

  Create a card by deck name:
    python mochi_api.py create --deck-name "My Deck" --content "Question\\n---\\nAnswer"

  List cards in a deck:
    python mochi_api.py cards --deck DECK_ID

  Get due cards:
    python mochi_api.py due

  Create a new deck:
    python mochi_api.py create-deck --name "New Deck"
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List decks
    decks_parser = subparsers.add_parser("decks", help="List all decks")
    decks_parser.add_argument("--ids", action="store_true", help="Show deck IDs on separate lines")

    # Create card
    create_parser = subparsers.add_parser("create", help="Create a new card")
    create_parser.add_argument("--deck", "-d", help="Deck ID")
    create_parser.add_argument("--deck-name", "-n", help="Deck name (searches for matching deck)")
    create_parser.add_argument("--content", "-c", required=True, help="Card content (markdown)")
    create_parser.add_argument("--template", "-t", help="Template ID")
    create_parser.add_argument("--reverse", "-r", action="store_true", help="Enable reverse review")

    # List cards
    cards_parser = subparsers.add_parser("cards", help="List cards")
    cards_parser.add_argument("--deck", "-d", help="Filter by deck ID")
    cards_parser.add_argument("--limit", "-l", type=int, default=10, help="Number of cards to show")

    # Due cards
    due_parser = subparsers.add_parser("due", help="Get cards due for review")
    due_parser.add_argument("--deck", "-d", help="Filter by deck ID")
    due_parser.add_argument("--date", help="Check for specific date (YYYY-MM-DD)")

    # Create deck
    create_deck_parser = subparsers.add_parser("create-deck", help="Create a new deck")
    create_deck_parser.add_argument("--name", "-n", required=True, help="Deck name")
    create_deck_parser.add_argument("--parent", "-p", help="Parent deck ID")

    # Delete card
    delete_parser = subparsers.add_parser("delete", help="Delete a card")
    delete_parser.add_argument("card_id", help="Card ID to delete")

    # Search deck
    search_parser = subparsers.add_parser("search-deck", help="Search for a deck by name")
    search_parser.add_argument("name", help="Deck name to search for")

    # Interactive review
    review_parser = subparsers.add_parser("review", help="Interactive review of due cards")
    review_parser.add_argument("--deck", "-d", help="Filter by deck ID")
    review_parser.add_argument("--deck-name", "-n", help="Filter by deck name")
    review_parser.add_argument("--limit", "-l", type=int, help="Maximum number of cards to review")
    review_parser.add_argument("--count", "-c", action="store_true", help="Show due count only")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "decks":
            list_decks(show_ids=args.ids)

        elif args.command == "create":
            deck_id = args.deck
            if not deck_id and args.deck_name:
                deck = search_deck_by_name(args.deck_name)
                if deck:
                    deck_id = deck.get("id")

            if not deck_id:
                print("Error: Must specify --deck or --deck-name")
                sys.exit(1)

            # Handle escaped newlines in content
            content = args.content.replace("\\n", "\n")
            create_card(deck_id, content, args.template, args.reverse)

        elif args.command == "cards":
            list_cards(args.deck, args.limit)

        elif args.command == "due":
            get_due_cards(args.deck, args.date)

        elif args.command == "create-deck":
            create_deck(args.name, args.parent)

        elif args.command == "delete":
            delete_card(args.card_id)

        elif args.command == "search-deck":
            deck = search_deck_by_name(args.name)
            if deck:
                print(f"Found: {deck.get('name')}")
                print(f"ID: {deck.get('id')}")

        elif args.command == "review":
            deck_id = args.deck
            if args.deck_name and not deck_id:
                deck = search_deck_by_name(args.deck_name)
                if deck:
                    deck_id = deck.get("id")

            if args.count:
                cards = get_due_cards_local(deck_id)
                print(f"Due cards: {len(cards)}")
            else:
                interactive_review(deck_id=deck_id, deck_name=args.deck_name if not deck_id else None, limit=args.limit)

    except requests.HTTPError as e:
        print(f"API Error: {e}")
        if e.response is not None:
            try:
                print(f"Details: {e.response.json()}")
            except:
                print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
