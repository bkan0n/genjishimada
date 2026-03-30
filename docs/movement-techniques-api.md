# Movement Techniques API — Frontend Integration Guide

**Base URL:** `/api/v3/content/movement-tech`

---

## Overview

The movement techniques API has two tiers:

- **Public endpoints** — no authentication required. Used by the public glossary page.
- **Admin endpoints** — require an API key with the `content:admin` scope. Used by the admin dashboard.

---

## Data Shapes

### Category
```json
{
  "id": 1,
  "name": "Wall Riding",
  "sort_order": 1
}
```

### Difficulty
```json
{
  "id": 1,
  "name": "Beginner",
  "sort_order": 1
}
```

### Technique (full)
```json
{
  "id": 1,
  "name": "Wall Jump",
  "description": "Jump off a wall to gain height.",
  "display_order": 1,
  "category_id": 2,
  "category_name": "Wall Riding",
  "difficulty_id": 1,
  "difficulty_name": "Beginner",
  "tips": [
    { "id": 10, "text": "Approach at a slight angle.", "sort_order": 1 }
  ],
  "videos": [
    { "id": 5, "url": "https://youtube.com/...", "caption": "Example clip", "sort_order": 1 }
  ]
}
```

`category_id`, `difficulty_id`, `category_name`, `difficulty_name`, `description`, and `caption` can all be `null`.

---

## Public Endpoints (no auth)

### List all categories
```
GET /api/v3/content/movement-tech/categories
```
**Response `200`:**
```json
{
  "categories": [ ...CategoryOut ]
}
```
**Use for:** populating the category filter/nav on the glossary page.

---

### List all difficulties
```
GET /api/v3/content/movement-tech/difficulties
```
**Response `200`:**
```json
{
  "difficulties": [ ...DifficultyOut ]
}
```
**Use for:** populating the difficulty filter on the glossary page.

---

### List all techniques
```
GET /api/v3/content/movement-tech/
```
**Response `200`:**
```json
{
  "techniques": [ ...TechniqueOut ]
}
```
Techniques are returned in `display_order` order. Tips and videos are nested inline — no second request needed.

**Use for:** rendering the full glossary page. You can filter/group client-side by `category_id` or `difficulty_id` since the full dataset is returned in one call.

---

## Admin Endpoints

All admin endpoints require the header:
```
X-API-KEY: <your-api-key>
```
The API key must have the `content:admin` scope. Requests without a valid key return `401`. Requests with a key that lacks the scope return `403`.

---

### Categories

#### Create a category
```
POST /api/v3/content/movement-tech/categories
```
**Body:**
```json
{ "name": "Wall Riding" }
```
**Response `201`:** `CategoryOut`

**Errors:**
- `409` — a category with that name already exists

---

#### Update a category
```
PUT /api/v3/content/movement-tech/categories/{id}
```
**Body:**
```json
{ "name": "Updated Name" }
```
**Response `200`:** `CategoryOut`

**Errors:**
- `404` — category not found
- `409` — name already taken

---

#### Delete a category
```
DELETE /api/v3/content/movement-tech/categories/{id}
```
**Response `204`:** no body

Deleting a category does **not** delete its techniques — it sets `category_id` to `null` on any technique that referenced it.

**Errors:**
- `404` — category not found

---

#### Reorder a category
```
POST /api/v3/content/movement-tech/categories/{id}/reorder
```
**Body:**
```json
{ "direction": "up" }
```
`direction` must be `"up"` or `"down"`. Moving the first item `"up"` or the last item `"down"` is a no-op (returns current order without error).

**Response `201`:** full `CategoryListResponse` (same shape as the GET list) — replace your local list with this.

**Errors:**
- `404` — category not found

---

### Difficulties

Identical shape to categories. Replace `categories` with `difficulties` and `{id}` with the difficulty ID.

| Action | Method | Path |
|--------|--------|------|
| Create | `POST` | `/difficulties` |
| Update | `PUT` | `/difficulties/{id}` |
| Delete | `DELETE` | `/difficulties/{id}` |
| Reorder | `POST` | `/difficulties/{id}/reorder` |

Same request/response shapes and error codes as categories.

---

### Techniques

#### Create a technique
```
POST /api/v3/content/movement-tech/techniques
```
**Body:**
```json
{
  "name": "Wall Jump",
  "description": "Jump off a wall to gain height.",
  "category_id": 2,
  "difficulty_id": 1,
  "tips": [
    { "text": "Approach at a slight angle.", "sort_order": 1 }
  ],
  "videos": [
    { "url": "https://youtube.com/...", "caption": "Example clip", "sort_order": 1 }
  ]
}
```
All fields except `name` are optional. `tips` and `videos` default to `[]`.

**Response `201`:** `TechniqueOut` (with DB-assigned IDs on tips and videos)

**Errors:**
- `400` — `category_id` or `difficulty_id` does not exist

---

#### Get a single technique
```
GET /api/v3/content/movement-tech/techniques/{id}
```
**Response `200`:** `TechniqueOut`

**Errors:**
- `404` — technique not found

---

#### Update a technique
```
PUT /api/v3/content/movement-tech/techniques/{id}
```
**Body** — all fields are optional; omit a field entirely to leave it unchanged:
```json
{
  "name": "New Name",
  "description": "Updated description.",
  "category_id": 3,
  "difficulty_id": null,
  "tips": [
    { "text": "New tip.", "sort_order": 1 }
  ],
  "videos": []
}
```

**Important — tips and videos use full-replace semantics:**
- **Omit** `tips` / `videos` → children are left exactly as they are.
- **Include** `tips` / `videos` (even as `[]`) → all existing tips/videos are deleted and replaced with what you send. There is no partial patch for individual tips — always send the complete desired list.

**Response `200`:** `TechniqueOut` (re-fetched from DB, includes new IDs for any new tips/videos)

**Errors:**
- `404` — technique not found
- `400` — `category_id` or `difficulty_id` does not exist

---

#### Delete a technique
```
DELETE /api/v3/content/movement-tech/techniques/{id}
```
**Response `204`:** no body

Tips and videos are deleted automatically.

**Errors:**
- `404` — technique not found

---

#### Reorder a technique
```
POST /api/v3/content/movement-tech/techniques/{id}/reorder
```
**Body:**
```json
{ "direction": "up" }
```
Same semantics as category/difficulty reorder.

**Response `201`:** full `TechniqueListResponse` — replace your local list with this.

**Errors:**
- `404` — technique not found

---

## Common Error Shape

All error responses return:
```json
{ "error": "Human-readable message" }
```

---

## Suggested Page Architecture

### Public glossary page
1. On load, fire **three requests in parallel:**
   - `GET /categories`
   - `GET /difficulties`
   - `GET /` (all techniques)
2. Render techniques list. Use `category_name` / `difficulty_name` directly from each technique — no join needed.
3. Use the categories and difficulties lists to populate filter UI.

### Admin dashboard
- Use the public `GET /` to load the initial list.
- After any create/update/delete/reorder, use the response body to refresh local state (reorder endpoints return the full updated list; create/update return the affected item; delete returns nothing so remove it locally).
- tip/video sort_order is determined by the order you send the array — set `sort_order` to the 1-based index of each item in your UI list.
