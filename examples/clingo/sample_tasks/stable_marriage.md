# Stable Marriage Problem

There are 3 men (Adam, Bob, Carl) and 3 women (Diana, Eve, Fiona).

Men's preferences (most to least preferred):
- Adam: Diana, Eve, Fiona
- Bob: Eve, Diana, Fiona  
- Carl: Diana, Fiona, Eve

Women's preferences (most to least preferred):
- Diana: Bob, Adam, Carl
- Eve: Adam, Carl, Bob
- Fiona: Carl, Bob, Adam

Find a stable matching where no man and woman who are not matched to each other would both prefer to be with each other over their current partners.

Output format (JSON):
```json
{
  "marriages": [
    {"man": "Adam", "woman": "woman_name"},
    {"man": "Bob", "woman": "woman_name"},
    {"man": "Carl", "woman": "woman_name"}
  ]
}
```