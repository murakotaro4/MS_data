from bs4 import BeautifulSoup

import ms_data.scraping.scrape_msdata as sm
from ms_data.scraping.detail_page import (
    apply_deployment_fallbacks,
    normalize_turn_values,
)


def test_parse_deployment_with_ids():
    html = '<div id="label_sortie_G_S"></div>'
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is True
    assert dep["出撃_宇宙可"] is True

    html = '<div id="label_sortie_G_n"></div>'
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is True
    assert dep["出撃_宇宙可"] is False

    html = '<div id="label_sortie_n_S"></div>'
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is False
    assert dep["出撃_宇宙可"] is True


def test_parse_env_suitability_with_ids():
    html = '<div id="label_env_G_S_W"></div>'
    soup = BeautifulSoup(html, "lxml")
    env = sm.parse_env_suitability(soup)
    assert env["環境適正_地上"] is True
    assert env["環境適正_宇宙"] is True
    assert env["環境適正_水中"] is True

    html = '<div id="label_env_n_n"></div>'
    soup = BeautifulSoup(html, "lxml")
    env = sm.parse_env_suitability(soup)
    assert env["環境適正_地上"] is False
    assert env["環境適正_宇宙"] is False
    assert env["環境適正_水中"] is False


def test_parse_deployment_ground_only_text():
    html = "<h3>出撃</h3><p>地上のみ</p>"
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is True
    assert dep["出撃_宇宙可"] is False


def test_parse_deployment_space_only_text():
    html = "<h3>出撃</h3><p>宇宙のみ</p>"
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is False
    assert dep["出撃_宇宙可"] is True


def test_parse_deployment_symbol_text():
    html = "<h3>出撃</h3><p>地上:◯ 宇宙:×</p>"
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is True
    assert dep["出撃_宇宙可"] is False


def test_parse_deployment_from_table():
    html = (
        "<h3>出撃</h3>"
        "<table><tr><td>地上</td><td>◯</td></tr>"
        "<tr><td>宇宙</td><td>×</td></tr></table>"
    )
    soup = BeautifulSoup(html, "lxml")
    dep = sm.parse_deployment(soup)
    assert dep["出撃_地上可"] is True
    assert dep["出撃_宇宙可"] is False


def test_parse_env_suitability_from_text():
    html = "<h3>環境適正</h3><p>地上:◯ 宇宙:× 水中:×</p>"
    soup = BeautifulSoup(html, "lxml")
    env = sm.parse_env_suitability(soup)
    assert env["環境適正_地上"] is True
    assert env["環境適正_宇宙"] is False
    assert env["環境適正_水中"] is False


def test_parse_env_suitability_multiple_headers_preserves_output(load_fixture):
    soup = BeautifulSoup(
        load_fixture("env_suitability_multiple_headers.html"), "lxml"
    )

    assert sm.parse_env_suitability(soup) == {
        "環境適正_地上": True,
        "環境適正_宇宙": False,
        "環境適正_水中": True,
    }


def test_apply_deployment_fallbacks_from_turn_keys():
    both = {1: {"旋回_地上_通常時": 70, "旋回_宇宙_通常時": 72}}
    apply_deployment_fallbacks(both, [1])
    assert both[1]["出撃_地上可"] is True
    assert both[1]["出撃_宇宙可"] is True

    ground_only = {1: {"旋回_地上_通常時": 70}}
    apply_deployment_fallbacks(ground_only, [1])
    assert ground_only[1]["出撃_地上可"] is True
    assert ground_only[1]["出撃_宇宙可"] is False

    space_only = {1: {"旋回_宇宙_通常時": 72}}
    apply_deployment_fallbacks(space_only, [1])
    assert space_only[1]["出撃_地上可"] is False
    assert space_only[1]["出撃_宇宙可"] is True


def test_normalize_turn_values_moves_keys_for_space_only():
    recs = {
        1: {
            "出撃_地上可": False,
            "出撃_宇宙可": True,
            "旋回_地上_通常時": 80,
            "旋回_地上_変形時": 75,
        }
    }
    normalize_turn_values(recs, [1])
    assert "旋回_地上_通常時" not in recs[1]
    assert "旋回_地上_変形時" not in recs[1]
    assert recs[1]["旋回_宇宙_通常時"] == 80
    assert recs[1]["旋回_宇宙_変形時"] == 75


def test_normalize_turn_values_moves_keys_for_ground_only():
    recs = {
        1: {
            "出撃_地上可": True,
            "出撃_宇宙可": False,
            "旋回_宇宙_通常時": 80,
            "旋回_宇宙_変形時": 75,
        }
    }
    normalize_turn_values(recs, [1])
    assert "旋回_宇宙_通常時" not in recs[1]
    assert "旋回_宇宙_変形時" not in recs[1]
    assert recs[1]["旋回_地上_通常時"] == 80
    assert recs[1]["旋回_地上_変形時"] == 75
