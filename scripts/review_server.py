#!/usr/bin/env python3
"""
Web-based SRS review server for Mochi cards.
Serves a review UI and syncs reviews back to Mochi API.
"""

import argparse
import os
import signal
import sys
import threading
import time
import webbrowser
from functools import wraps

from flask import Flask, jsonify, render_template, request

# Import from mochi_api
from mochi_api import get_due_cards_local, search_deck_by_name, submit_review

app = Flask(__name__)

# Global state
review_state = {
    "cards": [],
    "deck_name": None,
    "limit": None,
    "last_activity": time.time(),
    "reviewed_count": 0,
    "good_count": 0,
    "again_count": 0,
    "skipped_count": 0,
}

IDLE_TIMEOUT = 300  # 5 minutes


def update_activity():
    """Update last activity timestamp."""
    review_state["last_activity"] = time.time()


def check_idle_shutdown():
    """Background thread to check for idle timeout."""
    while True:
        time.sleep(30)
        if time.time() - review_state["last_activity"] > IDLE_TIMEOUT:
            print("\nIdle timeout reached. Shutting down...")
            os.kill(os.getpid(), signal.SIGTERM)
            break


@app.route("/")
def index():
    """Serve the review UI."""
    update_activity()
    return render_template("review.html")


@app.route("/api/cards")
def get_cards():
    """Return due cards as JSON."""
    update_activity()
    return jsonify({
        "cards": review_state["cards"],
        "deck_name": review_state["deck_name"],
        "total": len(review_state["cards"]),
    })


@app.route("/api/review", methods=["POST"])
def post_review():
    """Submit a review for a card."""
    update_activity()
    data = request.json
    card_id = data.get("card_id")
    remembered = data.get("remembered")
    skipped = data.get("skipped", False)

    if skipped:
        review_state["skipped_count"] += 1
        return jsonify({"status": "skipped"})

    if card_id is None or remembered is None:
        return jsonify({"error": "Missing card_id or remembered"}), 400

    # Submit to Mochi API
    try:
        submit_review(card_id, remembered)
        review_state["reviewed_count"] += 1
        if remembered:
            review_state["good_count"] += 1
        else:
            review_state["again_count"] += 1
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def get_stats():
    """Return review session statistics."""
    update_activity()
    return jsonify({
        "reviewed": review_state["reviewed_count"],
        "good": review_state["good_count"],
        "again": review_state["again_count"],
        "skipped": review_state["skipped_count"],
        "total": len(review_state["cards"]),
    })


@app.route("/api/done", methods=["POST"])
def done():
    """Signal that review is complete, trigger shutdown."""
    print("\nReview complete. Shutting down server...")
    # Schedule shutdown after response is sent
    threading.Thread(target=lambda: (time.sleep(0.5), os.kill(os.getpid(), signal.SIGTERM))).start()
    return jsonify({"status": "shutting_down"})


def main():
    parser = argparse.ArgumentParser(description="Web-based Mochi SRS review")
    parser.add_argument("--deck", "-d", help="Deck ID to review")
    parser.add_argument("--deck-name", "-n", help="Deck name to review")
    parser.add_argument("--limit", "-l", type=int, help="Maximum cards to review")
    parser.add_argument("--port", "-p", type=int, default=5111, help="Server port")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    # Resolve deck
    deck_id = args.deck
    deck_name = args.deck_name
    if deck_name and not deck_id:
        deck = search_deck_by_name(deck_name)
        if deck:
            deck_id = deck.get("id")
            deck_name = deck.get("name")
        else:
            print(f"Deck not found: {deck_name}")
            sys.exit(1)

    # Load cards
    print("Loading due cards from local database...")
    cards = get_due_cards_local(deck_id)

    if not cards:
        print("No cards due for review!")
        sys.exit(0)

    if args.limit and args.limit < len(cards):
        cards = cards[:args.limit]
        print(f"Found {len(cards)} cards (limited from more)")
    else:
        print(f"Found {len(cards)} cards due for review")

    # Store in global state
    review_state["cards"] = cards
    review_state["deck_name"] = deck_name or "All Decks"
    review_state["limit"] = args.limit

    # Start idle checker thread
    idle_thread = threading.Thread(target=check_idle_shutdown, daemon=True)
    idle_thread.start()

    # Open browser
    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        print(f"Opening browser to {url}")
        webbrowser.open(url)

    # Run server
    print(f"Server running on {url}")
    print("Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
