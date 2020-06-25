import pytest
import re
from warnings import warn

from ckanfunctionaltests.api import (
    extract_search_terms,
    get_example_response,
    validate_against_schema,
)
from ckanfunctionaltests.api.comparisons import AnySupersetOf
from ckanfunctionaltests.api.conftest import clean_unstable_elements


def test_package_list(base_url_3, rsession):
    response = rsession.get(f"{base_url_3}/action/package_list")
    assert response.status_code == 200
    validate_against_schema(response.json(), "package_list")

    assert response.json()["success"] is True


def test_package_show_404(base_url_3, rsession):
    response = rsession.get(f"{base_url_3}/action/package_show?id=plates-knives-and-forks")
    assert response.status_code == 404

    assert response.json()["success"] is False


def test_package_show(subtests, base_url_3, rsession, random_pkg_slug):
    response = rsession.get(f"{base_url_3}/action/package_show?id={random_pkg_slug}")
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_show")
        assert rj["success"] is True
        assert rj["result"]["name"] == random_pkg_slug
        assert all(res["package_id"] == rj['result']['id'] for res in rj["result"]["resources"])

    with subtests.test("uuid lookup consistency"):
        # we should be able to look up this same package by its uuid and get an identical response
        uuid_response = rsession.get(f"{base_url_3}/action/package_show?id={rj['result']['id']}")
        assert uuid_response.status_code == 200
        assert uuid_response.json() == rj

    with subtests.test("organization consistency"):
        org_response = rsession.get(
            f"{base_url_3}/action/organization_show?id={rj['result']['organization']['id']}"
        )
        assert org_response.status_code == 200
        assert org_response.json()["result"] == AnySupersetOf(rj['result']['organization'], recursive=True)


def test_package_show_default_schema(base_url_3, rsession, stable_pkg):
    # cannot use random slugs as they sometimes contain harvest packages which cannot be handled properly
    response = rsession.get(
        f"{base_url_3}/action/package_show?id={stable_pkg['name']}&use_default_schema=1"
    )
    assert response.status_code == 200
    rj = response.json()
    validate_against_schema(rj, "package_show")

    assert rj["success"] is True


def test_package_show_stable_pkg(subtests, base_url_3, rsession, stable_pkg):
    response = rsession.get(
        f"{base_url_3}/action/package_show?id={stable_pkg['name']}"
    )
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_show")
        assert rj["success"] is True

    clean_unstable_elements(rj["result"])
    clean_unstable_elements(stable_pkg)
    with subtests.test("response equality"):
        assert rj["result"] == AnySupersetOf(stable_pkg, recursive=True, seq_norm_order=True)


def test_package_show_stable_pkg_default_schema(
    subtests,
    base_url_3,
    rsession,
    stable_pkg_default_schema,
):
    clean_unstable_elements(stable_pkg_default_schema)
    response = rsession.get(
        f"{base_url_3}/action/package_show?id={stable_pkg_default_schema['name']}&use_default_schema=1"
    )
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_show")
        assert rj["success"] is True

    clean_unstable_elements(rj["result"])

    with subtests.test("response equality"):
        assert rj["result"] == stable_pkg_default_schema
        assert rj["result"] == AnySupersetOf(stable_pkg_default_schema, recursive=True, seq_norm_order=True)


def test_package_search_by_full_slug_general_term(
    subtests,
    inc_sync_sensitive,
    base_url_3,
    rsession,
    stable_pkg_slug,
):
    response = rsession.get(
        f"{base_url_3}/action/package_search?q={stable_pkg_slug}&rows=100"
    )
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_search")
        assert rj["success"] is True
        assert len(rj["result"]["results"]) <= 100

    if inc_sync_sensitive:
        desired_result = tuple(
            pkg for pkg in response.json()["result"]["results"] if pkg["name"] == stable_pkg_slug
        )
        assert desired_result
        if len(desired_result) > 1:
            warn(f"Multiple results ({len(desired_result)}) with name = {stable_pkg_slug!r})")

        with subtests.test("approx consistency with package_show"):
            ps_response = rsession.get(
                f"{base_url_3}/action/package_show?id={stable_pkg_slug}"
            )
            assert ps_response.status_code == 200
            assert any(
                ps_response.json()["result"]["id"] == result["id"] for result in desired_result
            )

            # TODO assert actual contents are approximately equal (exact equality is out the
            # window)


# revision_id is unstable, might have to skip this test to be able to run all the tests?
# or setup tests which are for dev stacks and staging environments
@pytest.mark.skip("revision_ids are unstable")
def test_package_search_by_revision_id_specific_field(
    subtests,
    inc_sync_sensitive,
    base_url_3,
    rsession,
    stable_pkg,
):
    response = rsession.get(
        f"{base_url_3}/action/package_search?fq=revision_id:{stable_pkg['revision_id']}"
        "&rows=1000"
    )

    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_search")
        assert rj["success"] is True
        assert len(rj["result"]["results"]) <= 1000

    with subtests.test("all results match criteria"):
        assert all(
            stable_pkg["revision_id"] == pkg["revision_id"] for pkg in rj["result"]["results"]
        )

    if inc_sync_sensitive:
        desired_result = tuple(
            pkg for pkg in rj["result"]["results"] if pkg["id"] == stable_pkg["id"]
        )
        assert len(desired_result) == 1

        with subtests.test("approx consistency with package_show"):
            assert stable_pkg["name"] == desired_result[0]["name"]
            assert stable_pkg["organization"] == desired_result[0]["organization"]
            # TODO assert actual contents are approximately equal (exact equality is out the
            # window)


def test_package_search_by_org_id_specific_field_and_title_general_term(
    subtests,
    inc_sync_sensitive,
    base_url_3,
    rsession,
    stable_pkg_search,
):
    stable_pkg = stable_pkg_search
    title_terms = extract_search_terms(stable_pkg["title"], 2)

    response = rsession.get(
        f"{base_url_3}/action/package_search?fq=owner_org:{stable_pkg['owner_org']}"
        f"&q={title_terms}&rows=1000"
    )
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_search")
        assert rj["success"] is True
        assert len(rj["result"]["results"]) <= 1000

    with subtests.test("all results match criteria"):
        assert all(
            stable_pkg["owner_org"] == pkg["owner_org"] for pkg in rj["result"]["results"]
        )
        # we can't reliably test for the search terms because they may have been stemmed
        # and not correspond to exact matches

    if inc_sync_sensitive:
        desired_result = tuple(
            pkg for pkg in rj["result"]["results"] if pkg["id"] == stable_pkg["id"]
        )
        if rj["result"]["count"] > 1000 and not desired_result:
            # we don't have all results - it may well be on a latter page
            warn(f"Expected package id {stable_pkg['id']!r} not found on first page of results")
        else:
            assert len(desired_result) == 1
            with subtests.test("approx consistency with package_show"):
                clean_unstable_elements(desired_result[0])
                clean_unstable_elements(stable_pkg["organization"], parent="organization")
                assert stable_pkg["name"] == desired_result[0]["name"]
                assert stable_pkg["organization"] \
                    == desired_result[0]["organization"]
                # TODO assert actual contents are approximately equal (exact equality is out
                # the window)


def test_package_search_facets(subtests, inc_sync_sensitive, base_url_3, rsession, random_pkg):
    notes_terms = extract_search_terms(random_pkg["notes"], 2)

    response = rsession.get(
        f"{base_url_3}/action/package_search?q={notes_terms}&rows=10"
        "&facet.field=[\"license_id\",\"organization\"]&facet.limit=-1"
    )
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_search")
        assert rj["success"] is True
        assert len(rj["result"]["results"]) <= 10

    if inc_sync_sensitive:
        with subtests.test("facets include random_pkg's value"):
            assert random_pkg["organization"]["name"] in rj["result"]["facets"]["organization"]
            assert any(
                random_pkg["organization"]["name"] == val["name"]
                for val in rj["result"]["search_facets"]["organization"]["items"]
            )

            # not all packages have a license_id
            if random_pkg.get("license_id"):
                assert random_pkg["license_id"] in rj["result"]["facets"]["license_id"]
                assert any(
                    random_pkg["license_id"] == val["name"]
                    for val in rj["result"]["search_facets"]["license_id"]["items"]
                )


def test_package_search_stable_package(subtests, base_url_3, rsession, stable_pkg_search):
    stable_pkg = stable_pkg_search
    response = rsession.get(
        f"{base_url_3}/action/package_search?q=name:{stable_pkg['name']}&rows=30"
    )
    assert response.status_code == 200
    rj = response.json()

    with subtests.test("response validity"):
        validate_against_schema(rj, "package_search")
        assert rj["success"] is True
        assert len(rj["result"]["results"]) <= 30

    desired_result = tuple(
        pkg for pkg in rj["result"]["results"] if pkg["name"] == stable_pkg["name"]
    )
    assert len(desired_result) == 1

    clean_unstable_elements(desired_result[0])
    clean_unstable_elements(stable_pkg)

    with subtests.test("desired result equality"):
        assert desired_result[0] == AnySupersetOf(stable_pkg, recursive=True, seq_norm_order=True)
