# Graph Coloring Problem

You have a graph with 4 nodes. The edges are:
- Node 1 is connected to Node 2
- Node 1 is connected to Node 3  
- Node 2 is connected to Node 3
- Node 2 is connected to Node 4
- Node 3 is connected to Node 4

Assign colors to each node such that no two connected nodes have the same color.
Use as few colors as possible.

Available colors: red, green, blue

Output format (JSON):
```json
{
  "coloring": {
    "1": "color",
    "2": "color", 
    "3": "color",
    "4": "color"
  },
  "colors_used": number
}
```