from bs4 import BeautifulSoup

import scripts.scrape_msdata as sm


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
