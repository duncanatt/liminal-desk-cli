"""Pure viewport scrolling helpers."""


def scroll_offset(current, action, page_size, row_count):
    """Clamp scrolling independently of terminal dimensions or payload wrapping."""
    end = max(0, row_count-page_size)
    if action == 'home':
        return 0
    if action == 'end':
        return end
    delta = {'down':1, 'up':-1, 'page_down':page_size, 'page_up':-page_size}.get(action, 0)
    return min(end, max(0, current+delta))
