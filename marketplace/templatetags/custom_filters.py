from django import template

register = template.Library()

@register.filter
def make_chunks(iterable, chunk_size):
    chunk_size = int(chunk_size)
    return [iterable[i:i + chunk_size] for i in range(0, len(iterable), chunk_size)]
