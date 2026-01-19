# Developer Utilities

This page lists helper classes used throughout the bot to keep common patterns consistent.

## Formatting Helpers

Location: `apps/bot/utilities/formatter.py`

A formattable model implements `to_format_dict()` and returns a mapping of display labels to string values.
The formatter uses this mapping to build a readable block for embeds and messages.

The interface lives in `apps/bot/utilities/formatter.py`:

```python
class FormattableProtocol(Protocol):
    def to_format_dict(self) -> dict[str, str | None]:
        ...
```

Two formatters are available:

- `Formatter` - draws a tree-like list with `┣`/`┗` prefix characters.
- `FilteredFormatter` - renders blockquote-style lines and lets you exclude fields.

Both drop keys whose values are `None`, `False`, or empty strings.

### Example: format a completion payload

`CompletionSubmissionModel` implements `to_format_dict()` in `apps/bot/utilities/completions.py`.

```python
from utilities.completions import CompletionSubmissionModel
from utilities.formatter import Formatter

model = CompletionSubmissionModel(**payload)
formatted = Formatter(model).format()

# Use in an embed description or message body
embed.description = formatted
```

### Example: filter fields

Use `FilteredFormatter` when you want a smaller summary:

```python
from utilities.maps import MapModel
from utilities.formatter import FilteredFormatter

model = MapModel(**payload)
formatted = FilteredFormatter(
    model,
    filter_fields={"Mechanics", "Restrictions"},
).format()
```

### Implementing a new formattable

Wrap SDK models or view models in a small class that implements `to_format_dict()`.

```python
class MyFormattable:
    def __init__(self, name: str, score: int) -> None:
        self.name = name
        self.score = score

    def to_format_dict(self) -> dict[str, str | None]:
        return {
            "Name": self.name,
            "Score": str(self.score),
        }
```

### Tips

- Keep keys short and consistent (`Code`, `Map`, `Time`).
- Return `""` for optional fields you want hidden.
- Use inline Markdown sparingly (e.g., `"[Link](...)"`).

## BaseView Helpers

Location: `apps/bot/utilities/base.py`

`BaseView` is the common base for Components V2 views. It handles timeouts and delegates errors to the shared
app command error handler. If you build a view on top of `BaseView`, you are in the same error handling flow as
the rest of the bot.

Key points:

- `rebuild_components()` is the hook you override to re-render the view.
- `_end_time_string` is updated on timeout and can be included in the UI.
- `on_error()` delegates to the app command error handler.

### Example: BaseView rebuild pattern

```python
from discord import ui
from utilities.base import BaseView

class MyView(BaseView):
    def rebuild_components(self) -> None:
        self.clear_items()
        container = ui.Container(
            ui.TextDisplay("# My View Title"),
            ui.Separator(),
            ui.TextDisplay("Body text goes here."),
            ui.Separator(),
            ui.TextDisplay(f"# {self._end_time_string}"),
        )
        self.add_item(container)
```

!!! important
    When you call `rebuild_components()` from inside a component callback, the component's `self.view` becomes `None`.
    If you need to reference the view after rebuilding, store it in a local variable before rebuilding.

## Pagination Helpers

Location: `apps/bot/utilities/paginator.py`

`PaginatorView` is a base view for paging through lists with buttons (next, previous, and page number).
It provides a consistent UI for multi-page results and handles view state for you.

Used by multiple extensions, for example:
- `apps/bot/extensions/completions.py` (leaderboards, user pages)
- `apps/bot/extensions/map_search.py` (search and guides)
- `apps/bot/extensions/moderator.py` (moderation panels)

### Example: paginator subclass

`PaginatorView` expects a title and a sequence of formattable items. You implement `build_page_body()` to render
the current page, and you can optionally add a second row via `build_additional_action_row()`.

```python
from discord import ui
from utilities.formatter import Formatter
from utilities.paginator import PaginatorView

class GuidePaginator(PaginatorView[FormattableGuide]):
    def build_page_body(self) -> list[ui.Item]:
        lines = []
        for item in self.current_page:
            lines.append(ui.TextDisplay(Formatter(item).format()))
        return lines

    def build_additional_action_row(self) -> ui.ActionRow | None:
        return ui.ActionRow(ui.Button(label="Refresh", custom_id="refresh"))

view = GuidePaginator("Guides", guides, page_size=5)
view.original_interaction = itx
await itx.response.send_message(view=view)
```

The paginator rebuilds its components on every page change by calling `rebuild_components()`.

!!! important
    The same `self.view` behavior applies inside pagination button callbacks. Save the view to a local variable
    before rebuilding if you need to reference it after the rebuild.

## Error Handling Helpers

Location: `apps/bot/utilities/errors.py`

- `UserFacingError` - Exceptions meant to show a clear message to the user.
- `ErrorView` - Standard error UI with a feedback button.

### Interaction behavior

- Any view that subclasses `BaseView` uses the shared error handler.
- If you raise `UserFacingError` inside an interaction, the error message is shown to the user.
- Any non-`UserFacingError` is shown as an unknown error.
- In both cases, users can submit feedback, which is sent to Sentry.

## Next Steps

- [Services & Extensions](../architecture/services.md)
- [Messaging & Queues](../architecture/messaging.md)
