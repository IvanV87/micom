"""Test optimization functions."""

from fixtures import community
import cobra
from cobra.util.solver import solvers
import numpy as np
import pytest

stable = ["glpk", "cplex"]
solvers = [s for s in solvers.keys() if s in stable]


def test_community_objective(community):
    x = community.optimize()

    assert isinstance(x, cobra.core.solution.Solution)
    assert np.allclose(x.f, 0.873922)


@pytest.mark.parametrize("solver", solvers)
def test_benchmark_community_objective(community, benchmark, solver):
    community.solver = solver
    benchmark(community.optimize)


def test_individual_objective(community):
    growth_rates = community.optimize_all()
    assert np.allclose(growth_rates, 0.873922)


@pytest.mark.parametrize("solver", solvers)
def test_benchmark_individual(community, benchmark, solver):
    community.solver = solver
    benchmark(community.optimize_single, 0)