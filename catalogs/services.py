def preview_next_category_code() -> str:
    """Best-effort preview of what ProductCategory.save() would assign
    next — reads CategoryCodeSequence.next_value without locking it
    (nothing is actually being created yet, so there's nothing to lock).
    The real save() always computes the authoritative value itself
    under select_for_update; this is only for showing the user what to
    expect before they click save. If two categories were created at
    the exact same instant this could be off by one — a non-issue at
    this app's real concurrency (1-2 users)."""
    from .models import CategoryCodeSequence

    sequence = CategoryCodeSequence.get_or_create_singleton()
    return str(sequence.next_value).zfill(2)


def preview_next_subcategory_code(category) -> str:
    """Same idea as preview_next_category_code, one level down — mirrors
    the MAX-based logic in ProductSubcategory.save() exactly (must stay
    in sync with it if that logic ever changes)."""
    from .models import ProductSubcategory

    existing_suffixes = [
        int(code[len(category.code) :])
        for code in ProductSubcategory.objects.filter(category=category).values_list(
            "code", flat=True
        )
        if code
    ]
    next_suffix = max(existing_suffixes, default=0) + 1
    return category.code + str(next_suffix).zfill(2)
