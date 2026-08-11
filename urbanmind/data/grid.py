"""500 m analysis grid and spatial blocking.

Spatial blocks (contiguous cell clusters) are the resampling unit of the unified
statistical protocol: grid cells are strongly spatially autocorrelated, so cell-level
resampling would understate uncertainty.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CityGrid:
    """Regular 500 m grid for one city.

    Cells are stored as (row, col) indices with a validity mask; observations and
    predictions are dense arrays of shape (T, n_rows, n_cols, n_domains).
    """

    name: str
    n_rows: int
    n_cols: int
    cell_size_m: float = 500.0
    valid: np.ndarray = field(default=None)  # bool (n_rows, n_cols)

    def __post_init__(self):
        if self.valid is None:
            self.valid = np.ones((self.n_rows, self.n_cols), dtype=bool)

    @property
    def n_valid(self) -> int:
        return int(self.valid.sum())

    def cell_coordinates(self) -> np.ndarray:
        """(n_valid, 2) array of (row, col) for valid cells, fixed ordering."""
        return np.argwhere(self.valid)


def make_spatial_blocks(grid: CityGrid, block_cells: int = 10, seed: int = 0) -> np.ndarray:
    """Partition valid cells into contiguous square blocks of ~block_cells x block_cells.

    Returns an integer block id per valid cell (aligned with grid.cell_coordinates()).
    Blocks are the exchangeable units for the cluster bootstrap in eval.stats.
    """
    coords = grid.cell_coordinates()
    block_row = coords[:, 0] // block_cells
    block_col = coords[:, 1] // block_cells
    n_block_cols = int(np.ceil(grid.n_cols / block_cells))
    block_id = block_row * n_block_cols + block_col
    # Re-index to consecutive ids for convenience.
    _, block_id = np.unique(block_id, return_inverse=True)
    return block_id
