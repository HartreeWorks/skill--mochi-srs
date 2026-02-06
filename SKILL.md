---
name: mochi-srs
description: This skill should be used when the user says "mem", "memorise", "flashcard", or mentions Mochi/SRS. Creates, lists, and reviews spaced repetition flashcards.
---

# Mochi SRS Card Creator

Create and manage spaced repetition flashcards in Mochi using their API.

## Prerequisites

1. **API Key**: Get a Mochi API key from the Mochi app (Settings > API)

2. **Configure the key**: Add the API key to `~/.claude/skills/mochi-srs/.env`:
   ```
   MOCHI_API_KEY=your_api_key_here
   ```

3. **Install dependencies** (first time only):
   ```bash
   pip install requests
   ```

## Card Format

Mochi cards use markdown. The standard format for question/answer cards:

```markdown
Question text here
---
Answer text here
```

The `---` separator divides the front (question) from the back (answer).

### Rich Content Support

Cards support full markdown:
- **Bold**, *italic*, `code`
- Lists (bulleted and numbered)
- Code blocks with syntax highlighting
- LaTeX math: `$inline$` or `$$block$$`
- Images via URLs

## Usage

### Creating Cards

Use the script at `~/.claude/skills/mochi-srs/scripts/mochi_api.py`.

**Single card by deck ID:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py create \
  --deck DECK_ID \
  --content "What is the capital of France?\n---\nParis"
```

**Single card by deck name:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py create \
  --deck-name "Geography" \
  --content "What is the capital of France?\n---\nParis"
```

### Listing Decks

First, list available decks to find the deck ID:

```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py decks
```

### Creating Multiple Cards

For multiple cards, call the create command multiple times or use the Python API directly:

```python
import sys
sys.path.insert(0, '/Users/ph/.claude/skills/mochi-srs/scripts')
from mochi_api import create_card

deck_id = "your-deck-id"
cards = [
    "Question 1\n---\nAnswer 1",
    "Question 2\n---\nAnswer 2",
]

for content in cards:
    create_card(deck_id, content)
```

### Other Commands

**List cards in a deck:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py cards --deck DECK_ID
```

**Get due cards (via API):**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py due
```

**Create a new deck:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py create-deck --name "New Deck"
```

**Search for a deck by name:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py search-deck "partial name"
```

### Interactive Review

Review due cards directly in the terminal. Reads from the local Mochi database for faster loading, syncs reviews back via the API.

**Start a review session:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py review
```

**Review a specific deck:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py review --deck DECK_ID
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py review --deck-name "2024"
```

**Just check due count:**
```bash
python ~/.claude/skills/mochi-srs/scripts/mochi_api.py review --count
```

**Controls during review:**
- `Enter` - Reveal answer
- `g` - Mark as Good (remembered)
- `a` - Mark as Again (forgot)
- `s` - Skip card
- `q` - Quit session

### Web Review UI

Open a browser-based review interface for a more visual experience:

**Start web review:**
```bash
python ~/.claude/skills/mochi-srs/scripts/review_server.py -n "2024" -l 10
```

**Options:**
- `--deck-name`, `-n` - Filter by deck name
- `--deck`, `-d` - Filter by deck ID
- `--limit`, `-l` - Maximum cards to review
- `--port`, `-p` - Server port (default 5111)
- `--no-browser` - Don't auto-open browser

**Web controls:**
- `Space` / `Enter` - Reveal answer
- `G` - Good (remembered)
- `A` - Again (forgot)
- `S` - Skip card
- Click "Done" to end session

The server auto-shuts down after 5 minutes of inactivity or when you click Done.

## Workflow

When user requests flashcard creation:

1. **Check for API key**: Verify `.env` file exists with `MOCHI_API_KEY`
2. **Check for default deck**: Look for `DEFAULT_DECK_ID` in `.env`. If not set, ask user which deck to use and offer to save it as default.
3. **Draft card content**: Format as `Front\n---\nBack`
4. **ALWAYS show for review**: Display the drafted card(s) and ask for confirmation before creating
5. **Create only after approval**: Only call the API after user confirms

**CRITICAL**: Never create cards without showing the content first and getting user approval.

## French Vocabulary Cards

When user provides French words or phrases:

- **Front**: English translation with French flag indicators: `🇫🇷 &nbsp; [English text] &nbsp; 🇫🇷`
  - Use British English spelling
  - The `&nbsp;` adds visual spacing between flags and text
- **Back**: French word/phrase
- **Keep it simple**: No extra info, pronunciation, or context unless requested
- **Correct mistakes**: Fix spelling, accents, and grammar errors in the French
  - Always use the corrected version on the card
  - Flag corrections to the user when showing the draft
  - Briefly explain non-obvious corrections (grammar, agreement, etc.)
  - No need to explain obvious fixes like typos or missing accents (é, è, ç, etc.)

Example input: "bonjour"
```
🇫🇷 &nbsp; Hello &nbsp; 🇫🇷
---
Bonjour
```

Example input: "je suis fatigué"
```
🇫🇷 &nbsp; I am tired &nbsp; 🇫🇷
---
Je suis fatigué
```

Example input: "heureux" (has masculine/feminine forms)
```
🇫🇷 &nbsp; Happy &nbsp; 🇫🇷
---
Heureux (M)
Heureuse (F)
```

For words with masculine/feminine variations, show both forms on the back, one per line, with (M) or (F) in brackets.

## Salsa Cards

When user provides salsa moves, techniques, or tips:

- **Front**: Dancer emoji indicators around the text: `💃 &nbsp; [Question/topic] &nbsp; 💃`
  - The `&nbsp;` adds visual spacing between emojis and text
- **Back**: The technique details, tips, or answer

Example input: "How to start Paseo?"
```
💃 &nbsp; How to start Paseo? &nbsp; 💃
---
Left arm starts going down at step 2, then finishes at step 3.
```

Example input: "Quick end of music move"
```
💃 &nbsp; Quick end of music move &nbsp; 💃
---
Pull left hand over my left shoulder, tip
```

### Bulk Card Display

When creating multiple cards, display them in a table for easy review:

| # | Front | Back | Notes |
|---|-------|------|-------|
| 1 | Hello | Bonjour | |
| 2 | Goodbye | Au revoir | |
| 3 | Happy | Heureux (M) / Heureuse (F) | |

- **Notes column**: Only include if there are corrections or remarks to flag
- Keep table cells concise; use "/" to separate M/F forms on one line
- After the table, summarise any corrections made

## Card Content Best Practices

- Keep cards simple and focused
- Use the `---` separator for front/back format
- Use cloze deletions for fill-in-the-blank: `{{cloze text}}`
- Add images via markdown: `![alt](url)`

## API Reference

Base URL: `https://app.mochi.cards/api/`

Key endpoints used:
- `POST /cards` - Create card (requires `content` and `deck-id`)
- `GET /decks` - List all decks
- `POST /decks` - Create deck (requires `name`)
- `GET /due` - Get cards due for review

Rate limit: 1 concurrent request per account.

## Troubleshooting

**"MOCHI_API_KEY not found"**: Add your API key to `~/.claude/skills/mochi-srs/.env`

**"401 Unauthorized"**: API key is invalid or expired. Generate a new one in Mochi settings.

**"429 Too Many Requests"**: Wait a moment and retry. Mochi limits to 1 concurrent request.

**Deck not found**: Use the `decks` command to list all decks and verify the ID.

## Update check

This skill is managed by [skills.sh](https://skills.sh). To check for updates, run `npx skills update`.
