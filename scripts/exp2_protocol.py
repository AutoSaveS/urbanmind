#!/usr/bin/env python3
"""Experiment 2 — protocol outline.

This file is a schematic, not an implementation. It fixes the order of the
stages, the objects passed between them and the reporting form, so the design
of Experiment 2 can be read in one page. Every stage that would touch data or
numbers is left as a stub.

The experiment asks whether cross-domain coupling carries transferable
information. Three coupling structures are fitted to the same intervention
outcomes and compared on records the fit never saw:

    primary      an intervention reaches only the domains it directly forces
    sequential   adds thermal -> air quality and thermal -> energy
    full         adds vegetation -> air quality and energy -> thermal

If the full structure transfers better than the sequential surrogate, coupling
carries information beyond the one-directional chain.

Usage:
    python scripts/exp2_protocol.py      # prints the stage order
"""

CLIMATES = ("mediterranean", "oceanic", "continental", "subtropical",
            "tropical_semiarid", "multi_region")
INTERVENTIONS = ("greening", "cool_roof", "retrofit", "low_emission_zone", "combined")
DOMAINS = ("thermal", "air_quality", "energy", "vegetation")
REGIMES = ("primary", "sequential", "full")

# Which domains each intervention acts on directly. All indirect response is
# what the coupling tensor is there to model.
DIRECT = {"greening": ("vegetation",),
          "cool_roof": ("thermal",),
          "retrofit": ("energy",),
          "low_emission_zone": ("air_quality",),
          "combined": ("thermal", "vegetation")}

# Pathways enabled beyond the direct ones, per regime.
PATHWAYS = {"primary": (),
            "sequential": (("thermal", "air_quality"), ("thermal", "energy")),
            "full": (("thermal", "air_quality"), ("thermal", "energy"),
                     ("vegetation", "air_quality"), ("energy", "thermal"))}


def load_library():
    """Read the Track B intervention-outcome library and its split table.

    Returns one observation per (record, domain), each carrying the climate
    group, intervention type, subset label, publication DOI and study site.
    Effect sizes are used in their reported units; no cross-domain rescaling
    happens at this stage.
    """
    raise NotImplementedError("see the released library and assignment table")


def verify_split(observations):
    """Re-check that no publication or study site spans both subsets.

    The assignment is fixed before any model is fitted; this call only
    confirms that the file on disk still matches that assignment.
    """
    raise NotImplementedError


def build_features(observations, regime):
    """Encode each observation as (climate, intervention, reachable domains).

    Reachability is the regime's direct domains closed under its pathway set,
    so the feature vector differs between regimes only through which
    intervention-domain combinations are active.
    """
    raise NotImplementedError


def fit(observations, regime):
    """Fit one regime on the fine-tuning subset only."""
    raise NotImplementedError


def score(model, observations):
    """Predict held-out observations and return one error per observation.

    Errors are made comparable across domains by dividing by the IQR of the
    validation observations for that domain, so a large-scale domain such as
    surface temperature does not dominate a small-scale one.
    """
    raise NotImplementedError


def case_grid(errors, observations):
    """Group errors into climate × pathway cells and keep those with enough
    validation studies. Each cell carries the three regimes' errors.
    """
    raise NotImplementedError


def compare(errors, observations):
    """Per cell, report CDTE for each regime and the reduction of full over
    sequential. Uncertainty comes from a paired cluster bootstrap with
    publications as clusters, followed by Holm correction over the grid.
    """
    raise NotImplementedError


def main():
    """Stage order, with the objects each stage hands to the next."""
    stages = [
        ("load", "library + assignment table -> observations"),
        ("verify", "observations -> assertions on the split"),
        ("fit", "fine-tuning observations -> primary, sequential, full"),
        ("score", "validation observations -> per-observation errors"),
        ("grid", "errors -> climate x pathway cells"),
        ("compare", "cells -> CDTE per regime, reduction, corrected p"),
    ]
    print(__doc__.strip())
    print("\nstages")
    for i, (name, flow) in enumerate(stages, 1):
        print(f"  {i}. {name:<8}{flow}")
    print("\nreported per cell: n studies, CDTE by regime, "
          "reduction of full over sequential, corrected p")
    print("reported overall: mean reduction with cluster-bootstrap CI, pass count")


if __name__ == "__main__":
    main()
