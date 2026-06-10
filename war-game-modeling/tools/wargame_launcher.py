#!/usr/bin/env python3
"""Local web launcher for the war-game CLI.

This tool intentionally lives beside the existing simulation code without
modifying it. It wraps `simulation.py` as a subprocess, streams logs to a
browser UI, and snapshots outputs into per-run folders.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import unquote, urlparse

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced through /api/defaults
    yaml = None


PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_DIR / "config.yaml"
RUNS_DIR = PROJECT_DIR / "runs"
DEPLOYMENTS_DIR = PROJECT_DIR / "deployments"
LOG_TAIL_LIMIT = 1200
UNIT_TYPES = ["RIFLE", "ANTI_TANK", "TANK", "ARTILLERY", "DRONE", "SELF_DEST_DRONE", "COMMAND_POST"]
COUNT_KEYS = {
    ("RED", "ARTILLERY"): "num_artillery_red",
    ("BLUE", "ARTILLERY"): "num_artillery_blue",
    ("RED", "DRONE"): "num_drone_red",
    ("BLUE", "DRONE"): "num_drone_blue",
    ("RED", "TANK"): "num_tank_red",
    ("BLUE", "TANK"): "num_tank_blue",
    ("RED", "ANTI_TANK"): "num_at_red",
    ("BLUE", "ANTI_TANK"): "num_at_blue",
    ("RED", "RIFLE"): "num_infantry_red",
    ("BLUE", "RIFLE"): "num_infantry_blue",
    ("RED", "COMMAND_POST"): "num_cp_red",
    ("BLUE", "COMMAND_POST"): "num_cp_blue",
    ("RED", "SELF_DEST_DRONE"): "num_self_dest_drone_red",
    ("BLUE", "SELF_DEST_DRONE"): "num_self_dest_drone_blue",
}
SYMBOLS = {
    "RIFLE": "INF",
    "ANTI_TANK": "AT",
    "TANK": "TNK",
    "ARTILLERY": "ART",
    "DRONE": "DRN",
    "SELF_DEST_DRONE": "SDD",
    "COMMAND_POST": "CP",
}


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>War Game Launcher</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --panel-2: #eef3f8;
      --line: #d8e0ea;
      --text: #16202a;
      --muted: #667587;
      --blue: #2367d1;
      --red: #b83d4c;
      --green: #2c7a52;
      --amber: #a86611;
      --shadow: 0 10px 24px rgba(17, 31, 46, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
    }

    button, input, select {
      font: inherit;
    }

    .app {
      display: grid;
      grid-template-columns: minmax(360px, 440px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      min-height: 100vh;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }

    .settings {
      padding: 18px;
      align-self: start;
      position: sticky;
      top: 18px;
      max-height: calc(100vh - 36px);
      overflow: auto;
    }

    .main {
      display: grid;
      grid-template-rows: auto auto auto 1fr;
      gap: 18px;
      min-height: calc(100vh - 36px);
    }

    h1 {
      font-size: 22px;
      margin: 0 0 4px;
      line-height: 1.2;
    }

    h2 {
      font-size: 15px;
      margin: 0;
      line-height: 1.25;
    }

    .subtle {
      color: var(--muted);
      font-size: 13px;
    }

    .section {
      border-top: 1px solid var(--line);
      margin-top: 16px;
      padding-top: 16px;
    }

    .grid-2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    label.field {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    input[type="number"] {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 0 10px;
    }

    input[type="text"], select {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 0 10px;
    }

    .toggles {
      display: grid;
      gap: 10px;
    }

    .toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 44px;
    }

    .toggle span {
      font-size: 14px;
      font-weight: 650;
    }

    .toggle input {
      width: 18px;
      height: 18px;
      accent-color: var(--blue);
      flex: 0 0 auto;
    }

    .preset-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .btn {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 700;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
    }

    .btn:hover {
      transform: translateY(-1px);
      border-color: #b6c6d8;
    }

    .btn.primary {
      background: var(--blue);
      color: #fff;
      border-color: var(--blue);
    }

    .btn.danger {
      background: #fff1f2;
      color: var(--red);
      border-color: #efb5bd;
    }

    .btn.active {
      background: #263541;
      color: #fff;
      border-color: #263541;
    }

    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
    }

    .actions {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 110px;
      gap: 10px;
      margin-top: 16px;
    }

    .deploy-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }

    .status {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 14px;
    }

    .metric {
      min-height: 72px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      display: grid;
      align-content: center;
      gap: 4px;
    }

    .metric b {
      font-size: 20px;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }

    .metric span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .command {
      padding: 14px;
    }

    .map-panel {
      display: grid;
      grid-template-rows: auto 1fr;
      overflow: hidden;
      height: var(--map-panel-height, 620px);
      min-height: 420px;
    }

    .map-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }

    .map-controls {
      display: grid;
      grid-template-columns: 80px 170px;
      align-items: center;
      gap: 8px;
      min-width: 260px;
    }

    .map-controls label {
      display: grid;
      grid-template-columns: auto 1fr;
      align-items: center;
      gap: 8px;
    }

    input[type="range"] {
      width: 100%;
      accent-color: var(--blue);
    }

    .map-wrap {
      min-height: 0;
      overflow: auto;
      background:
        linear-gradient(90deg, rgba(22,32,42,0.06) 1px, transparent 1px),
        linear-gradient(0deg, rgba(22,32,42,0.06) 1px, transparent 1px),
        #dce5ef;
      background-size: 40px 40px;
      display: grid;
      place-items: start center;
      padding: 12px;
    }

    #mapCanvas {
      max-width: 100%;
      height: auto;
      border: 1px solid #b7c4d3;
      border-radius: 6px;
      background: #eff4f8;
      cursor: crosshair;
    }

    .placement-list {
      max-height: 130px;
      overflow: auto;
      display: grid;
      gap: 6px;
      margin-top: 10px;
      padding-right: 2px;
    }

    .placement-item {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 8px;
      background: #fff;
      color: var(--text);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
    }

    .placement-item.active {
      border-color: var(--blue);
      background: #eef5ff;
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 12px;
      line-height: 1.45;
    }

    .codebox {
      background: #101820;
      color: #d8e7f5;
      border-radius: 8px;
      padding: 12px;
      min-height: 52px;
    }

    .log-panel {
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-height: 360px;
      overflow: hidden;
    }

    .log-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }

    .log {
      background: #0d1117;
      color: #d7e2ef;
      overflow: auto;
      padding: 14px;
      min-height: 280px;
    }

    .outputs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 14px;
      border-top: 1px solid var(--line);
      background: #fff;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--text);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      background: var(--panel-2);
    }

    .ok { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }

    @media (max-width: 980px) {
      .app {
        grid-template-columns: 1fr;
      }

      .settings {
        position: static;
        max-height: none;
      }

      .status {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="panel settings">
      <h1>War Game Launcher</h1>
      <div class="subtle" id="configPath">Loading config...</div>

      <div class="section">
        <h2>Presets</h2>
        <div class="preset-row" style="margin-top: 10px;">
          <button class="btn" data-preset="fast">Data run</button>
          <button class="btn" data-preset="visual">Visual debug</button>
          <button class="btn" data-preset="video">Video run</button>
          <button class="btn" data-preset="cli">Default</button>
        </div>
      </div>

      <div class="section grid-2">
        <label class="field">Time scale
          <input id="timeScale" type="number" min="0.1" step="0.1" value="5.0">
        </label>
        <label class="field">Sim speed
          <input id="simSpeed" type="number" min="0.1" step="0.1" value="1.0">
        </label>
        <label class="field">Max time
          <input id="maxTime" type="number" min="1" step="1" value="120">
        </label>
        <label class="field">Log tail
          <input id="logTail" type="number" min="100" step="100" value="500">
        </label>
      </div>

      <div class="section toggles">
        <label class="toggle"><span>Show detection lines</span><input id="detection" type="checkbox" checked></label>
        <label class="toggle"><span>Show eligible target lines</span><input id="eligible" type="checkbox" checked></label>
        <label class="toggle"><span>Show fire lines</span><input id="fire" type="checkbox" checked></label>
        <label class="toggle"><span>Disable video</span><input id="noVideo" type="checkbox"></label>
        <label class="toggle"><span>Close when finished</span><input id="noHold" type="checkbox"></label>
      </div>

      <div class="section">
        <h2>Deployment</h2>
        <div class="subtle" id="deploymentStatus" style="margin-top: 4px;">Loading map...</div>
        <div class="grid-2" style="margin-top: 12px;">
          <label class="field" style="grid-column: 1 / -1;">Map
            <select id="mapSelect"></select>
          </label>
          <label class="field">Team
            <select id="teamSelect">
              <option value="RED">RED</option>
              <option value="BLUE">BLUE</option>
            </select>
          </label>
          <label class="field">Platform
            <select id="unitSelect"></select>
          </label>
          <label class="field">Quantity
            <input id="quantityInput" type="number" min="1" step="1" value="1">
          </label>
          <label class="field">Saved file
            <select id="deploymentFiles"></select>
          </label>
          <label class="field" style="grid-column: 1 / -1;">Local JSON
            <input id="deploymentUpload" type="file" accept="application/json,.json">
          </label>
        </div>
        <div class="deploy-actions">
          <button id="addSelectedBtn" class="btn primary">Add selected</button>
          <button id="drawTrenchBtn" class="btn">Draw trench</button>
          <button id="cancelTrenchBtn" class="btn" disabled>Cancel trench</button>
          <button id="clearDeploymentBtn" class="btn">Clear map</button>
          <button id="loadDeploymentBtn" class="btn" disabled>Load saved</button>
          <button id="loadLocalDeploymentBtn" class="btn">Load local</button>
        </div>
        <label class="field" style="margin-top: 10px;">Save name
          <input id="deploymentName" type="text" value="manual_deployment">
        </label>
        <div class="deploy-actions">
          <button id="saveDeploymentBtn" class="btn">Save deployment</button>
          <button id="saveAsDeploymentBtn" class="btn">Save as new</button>
          <button id="downloadDeploymentBtn" class="btn">Download JSON</button>
          <button id="deletePlacementBtn" class="btn danger">Delete selected</button>
        </div>
        <div class="toggles" style="margin-top: 10px;">
          <label class="toggle"><span>Use manual deployment</span><input id="useDeployment" type="checkbox" checked></label>
        </div>
        <div class="placement-list" id="placementList"></div>
      </div>

      <div class="actions">
        <button id="runBtn" class="btn primary">Run simulation</button>
        <button id="stopBtn" class="btn danger" disabled>Stop</button>
      </div>
    </section>

    <section class="main">
      <section class="panel status">
        <div class="metric"><span>Status</span><b id="statusText">Idle</b></div>
        <div class="metric"><span>Run ID</span><b id="runId">-</b></div>
        <div class="metric"><span>Exit code</span><b id="exitCode">-</b></div>
        <div class="metric"><span>Elapsed</span><b id="elapsed">-</b></div>
      </section>

      <section class="panel map-panel">
        <div class="map-head">
          <div>
            <h2>Deployment Map</h2>
            <div class="subtle" id="mapHint">Click to choose a position, then add selected platform.</div>
          </div>
          <div class="map-controls">
            <div class="subtle" id="mapCoords">x: -, y: -</div>
            <label class="subtle">Height <input id="mapHeightSlider" type="range" min="420" max="1600" step="20" value="620"></label>
          </div>
        </div>
        <div class="map-wrap">
          <canvas id="mapCanvas" width="1200" height="875"></canvas>
        </div>
      </section>

      <section class="panel command">
        <h2 style="margin-bottom: 10px;">Command Preview</h2>
        <div class="codebox"><pre id="commandPreview"></pre></div>
      </section>

      <section class="panel log-panel">
        <div class="log-head">
          <div>
            <h2>Run Log</h2>
            <div class="subtle" id="runDir">No run yet</div>
          </div>
          <button id="clearLogBtn" class="btn">Clear view</button>
        </div>
        <div class="log"><pre id="logText"></pre></div>
        <div class="outputs" id="outputs"></div>
      </section>
    </section>
  </main>

  <script>
    const ids = {
      timeScale: document.getElementById("timeScale"),
      simSpeed: document.getElementById("simSpeed"),
      maxTime: document.getElementById("maxTime"),
      logTail: document.getElementById("logTail"),
      detection: document.getElementById("detection"),
      eligible: document.getElementById("eligible"),
      fire: document.getElementById("fire"),
      noVideo: document.getElementById("noVideo"),
      noHold: document.getElementById("noHold"),
      mapSelect: document.getElementById("mapSelect"),
      teamSelect: document.getElementById("teamSelect"),
      unitSelect: document.getElementById("unitSelect"),
      quantityInput: document.getElementById("quantityInput"),
      deploymentFiles: document.getElementById("deploymentFiles"),
      deploymentUpload: document.getElementById("deploymentUpload"),
      deploymentName: document.getElementById("deploymentName"),
      useDeployment: document.getElementById("useDeployment"),
      mapHeightSlider: document.getElementById("mapHeightSlider"),
    };

    const runBtn = document.getElementById("runBtn");
    const stopBtn = document.getElementById("stopBtn");
    const commandPreview = document.getElementById("commandPreview");
    const statusText = document.getElementById("statusText");
    const runId = document.getElementById("runId");
    const exitCode = document.getElementById("exitCode");
    const elapsed = document.getElementById("elapsed");
    const logText = document.getElementById("logText");
    const runDir = document.getElementById("runDir");
    const outputs = document.getElementById("outputs");
    const configPath = document.getElementById("configPath");
    const canvas = document.getElementById("mapCanvas");
    const ctx = canvas.getContext("2d");
    const deploymentStatus = document.getElementById("deploymentStatus");
    const placementList = document.getElementById("placementList");
    const mapCoords = document.getElementById("mapCoords");
    const mapHint = document.getElementById("mapHint");
    const mapPanel = document.querySelector(".map-panel");
    const mapImage = new Image();

    let clearedAt = 0;
    let deployment = { version: 1, name: "manual_deployment", mapPath: "", mapWidth: 1200, mapHeight: 875, placements: [], trenches: [] };
    let maps = [];
    let symbols = {};
    let squadSizes = {};
    let selectedPlacementId = null;
    let selectedTrenchId = null;
    let dragPlacementId = null;
    let dragTrench = null;
    let pendingPoint = null;
    let drawingTrench = false;
    let trenchDraft = [];
    let loadedDeploymentFile = "";

    function payload() {
      const maxTime = ids.maxTime.value.trim();
      return {
        timeScale: ids.timeScale.value,
        simSpeed: ids.simSpeed.value,
        maxTime: maxTime === "" ? null : maxTime,
        showDetection: ids.detection.checked,
        showEligibleTargets: ids.eligible.checked,
        showFire: ids.fire.checked,
        noVideo: ids.noVideo.checked,
        noHold: ids.noHold.checked,
        useDeployment: ids.useDeployment.checked,
        deployment: ids.useDeployment.checked ? structuredClone(deployment) : null,
      };
    }

    function commandParts(p) {
      const parts = ["python", "simulation.py"];
      parts.push("--time-scale", String(p.timeScale || "5.0"));
      parts.push("--sim_speed", String(p.simSpeed || "1.0"));
      parts.push("--detection", p.showDetection ? "T" : "F");
      parts.push("--eligible_TL", p.showEligibleTargets ? "T" : "F");
      parts.push("--fire", p.showFire ? "T" : "F");
      if (p.maxTime !== null && p.maxTime !== "") parts.push("--max-time", String(p.maxTime));
      if (p.noHold) parts.push("--no-hold");
      if (p.noVideo) parts.push("--no-video");
      return parts;
    }

    function updatePreview() {
      const p = payload();
      const extra = p.useDeployment ? "\n# manual deployment will be applied in this run workspace" : "";
      commandPreview.textContent = commandParts(p).join(" ") + extra;
    }

    function setPreset(name) {
      if (name === "fast") {
        ids.timeScale.value = "5.0";
        ids.simSpeed.value = "1.0";
        ids.maxTime.value = "600";
        ids.detection.checked = true;
        ids.eligible.checked = true;
        ids.fire.checked = true;
        ids.noVideo.checked = true;
        ids.noHold.checked = true;
      }
      if (name === "visual") {
        ids.timeScale.value = "2.0";
        ids.simSpeed.value = "1.0";
        ids.maxTime.value = "300";
        ids.detection.checked = true;
        ids.eligible.checked = true;
        ids.fire.checked = true;
        ids.noVideo.checked = true;
        ids.noHold.checked = true;
      }
      if (name === "video") {
        ids.timeScale.value = "5.0";
        ids.simSpeed.value = "1.0";
        ids.maxTime.value = "600";
        ids.detection.checked = false;
        ids.eligible.checked = false;
        ids.fire.checked = true;
        ids.noVideo.checked = false;
        ids.noHold.checked = true;
      }
      if (name === "cli") {
        ids.timeScale.value = "5.0";
        ids.simSpeed.value = "1.0";
        ids.maxTime.value = "";
        ids.detection.checked = true;
        ids.eligible.checked = true;
        ids.fire.checked = true;
        ids.noVideo.checked = false;
        ids.noHold.checked = false;
      }
      updatePreview();
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || "Request failed");
      return body;
    }

    async function loadDefaults() {
      try {
        const data = await api("/api/defaults");
        configPath.textContent = data.configPath;
        if (data.config && data.config.maxTime) {
          ids.maxTime.placeholder = String(data.config.maxTime);
        }
      } catch (err) {
        configPath.textContent = err.message;
      }
    }

    function selectedMap() {
      return maps.find((item) => item.path === ids.mapSelect.value);
    }

    function normalizedPoint(point) {
      if (Array.isArray(point)) {
        return { x: Number(point[0]), y: Number(point[1]) };
      }
      return { x: Number(point.x), y: Number(point.y) };
    }

    function normalizeTrenchPoints(points) {
      return (points || [])
        .slice(0, 4)
        .map(normalizedPoint)
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
    }

    function setDeployment(nextDeployment) {
      deployment = {
        version: 1,
        name: nextDeployment.name || "manual_deployment",
        mapPath: nextDeployment.mapPath,
        mapWidth: Number(nextDeployment.mapWidth || 1200),
        mapHeight: Number(nextDeployment.mapHeight || 875),
        placements: (nextDeployment.placements || []).map((item, index) => ({
          id: item.id || "placement_" + Date.now() + "_" + index,
          team: item.team,
          unitType: item.unitType,
          x: Number(item.x),
          y: Number(item.y),
          quantity: Math.max(1, Number(item.quantity || 1)),
        })),
        trenches: (nextDeployment.trenches || []).map((item, index) => ({
          id: item.id || "trench_" + Date.now() + "_" + index,
          points: normalizeTrenchPoints(item.points),
        })).filter((item) => item.points.length === 4),
      };
      ids.deploymentName.value = deployment.name || "manual_deployment";
      ids.mapSelect.value = deployment.mapPath;
      selectedPlacementId = null;
      selectedTrenchId = null;
      pendingPoint = null;
      drawingTrench = false;
      trenchDraft = [];
      updateTrenchButtons();
      loadMapImage();
      renderDeployment();
      updatePreview();
    }

    function setBlankDeployment(mapPath) {
      const map = maps.find((item) => item.path === mapPath) || maps[0];
      deployment = {
        version: 1,
        name: "manual_deployment",
        mapPath: map ? map.path : "",
        mapWidth: 0,
        mapHeight: 0,
        placements: [],
        trenches: [],
      };
      ids.deploymentName.value = "manual_deployment";
      if (map) ids.mapSelect.value = map.path;
      selectedPlacementId = null;
      selectedTrenchId = null;
      pendingPoint = null;
      drawingTrench = false;
      trenchDraft = [];
      loadedDeploymentFile = "";
      updateTrenchButtons();
      loadMapImage();
      renderDeployment();
      deploymentStatus.textContent = "No deployment loaded";
      updatePreview();
    }

    function updateLoadDeploymentButton() {
      const button = document.getElementById("loadDeploymentBtn");
      button.disabled = !ids.deploymentFiles.value;
    }

    function refreshDeploymentFiles(items) {
      ids.deploymentFiles.innerHTML = "";
      const prompt = document.createElement("option");
      prompt.value = "";
      prompt.textContent = "Choose saved deployment";
      ids.deploymentFiles.appendChild(prompt);
      if (!items || items.length === 0) {
        return;
      }
      for (const item of items) {
        const option = document.createElement("option");
        option.value = item.file;
        option.textContent = item.name;
        ids.deploymentFiles.appendChild(option);
      }
      updateLoadDeploymentButton();
    }

    async function loadDeploymentDefaults() {
      try {
        const data = await api("/api/deployment");
        maps = data.maps || [];
        symbols = data.symbols || {};
        squadSizes = data.squadSizes || {};
        ids.mapSelect.innerHTML = "";
        for (const item of maps) {
          const option = document.createElement("option");
          option.value = item.path;
          option.textContent = item.name;
          ids.mapSelect.appendChild(option);
        }
        ids.unitSelect.innerHTML = "";
        for (const unitType of data.unitTypes || []) {
          const option = document.createElement("option");
          option.value = unitType;
          option.textContent = (symbols[unitType] || unitType) + " - " + unitType;
          ids.unitSelect.appendChild(option);
        }
        refreshDeploymentFiles(data.deployments || []);
        setBlankDeployment(maps[0] && maps[0].path);
        setQuantityFromSquad();
      } catch (err) {
        deploymentStatus.textContent = err.message;
      }
    }

    function setQuantityFromSquad() {
      const teamSizes = squadSizes[ids.teamSelect.value] || {};
      const size = teamSizes[ids.unitSelect.value] || 1;
      ids.quantityInput.value = String(size);
    }

    function loadMapImage() {
      const map = selectedMap();
      canvas.width = deployment.mapWidth || 1200;
      canvas.height = deployment.mapHeight || 875;
      if (!map) {
        drawMap();
        return;
      }
      mapImage.onload = () => {
        if (!deployment.mapWidth || !deployment.mapHeight) {
          deployment.mapWidth = mapImage.naturalWidth;
          deployment.mapHeight = mapImage.naturalHeight;
          canvas.width = deployment.mapWidth;
          canvas.height = deployment.mapHeight;
        }
        drawMap();
      };
      mapImage.onerror = () => drawMap();
      mapImage.src = map.url + "?v=" + encodeURIComponent(map.path);
    }

    function canvasPoint(event) {
      const rect = canvas.getBoundingClientRect();
      const x = Math.round((event.clientX - rect.left) * (canvas.width / rect.width));
      const y = Math.round((event.clientY - rect.top) * (canvas.height / rect.height));
      return {
        x: Math.max(0, Math.min(canvas.width, x)),
        y: Math.max(0, Math.min(canvas.height, y)),
      };
    }

    function clampMapPoint(point) {
      return {
        x: Math.max(0, Math.min(canvas.width, Math.round(point.x))),
        y: Math.max(0, Math.min(canvas.height, Math.round(point.y))),
      };
    }

    function findPlacement(point) {
      for (let i = deployment.placements.length - 1; i >= 0; i -= 1) {
        const item = deployment.placements[i];
        const dx = point.x - item.x;
        const dy = point.y - item.y;
        if (Math.sqrt(dx * dx + dy * dy) <= 16) return item;
      }
      return null;
    }

    function distanceToSegment(point, start, end) {
      const vx = end.x - start.x;
      const vy = end.y - start.y;
      const wx = point.x - start.x;
      const wy = point.y - start.y;
      const lengthSq = vx * vx + vy * vy;
      const t = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, (wx * vx + wy * vy) / lengthSq));
      const px = start.x + t * vx;
      const py = start.y + t * vy;
      const dx = point.x - px;
      const dy = point.y - py;
      return Math.sqrt(dx * dx + dy * dy);
    }

    function pointInPolygon(point, points) {
      let inside = false;
      for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
        const xi = points[i].x;
        const yi = points[i].y;
        const xj = points[j].x;
        const yj = points[j].y;
        const intersects = ((yi > point.y) !== (yj > point.y)) &&
          (point.x < ((xj - xi) * (point.y - yi)) / (yj - yi || 1) + xi);
        if (intersects) inside = !inside;
      }
      return inside;
    }

    function findTrenchHit(point) {
      for (let i = (deployment.trenches || []).length - 1; i >= 0; i -= 1) {
        const trench = deployment.trenches[i];
        if (trench.id === selectedTrenchId) continue;
        const hit = trenchHit(trench, point, 13, 9);
        if (hit) return hit;
      }
      return null;
    }

    function trenchHit(trench, point, cornerRadius, edgeRadius) {
      const points = trench.points || [];
      if (points.length !== 4) return null;
      for (let index = 0; index < points.length; index += 1) {
        const corner = points[index];
        const dx = point.x - corner.x;
        const dy = point.y - corner.y;
        if (Math.sqrt(dx * dx + dy * dy) <= cornerRadius) {
          return { trench, pointIndex: index };
        }
      }
      for (let index = 0; index < points.length; index += 1) {
        const next = points[(index + 1) % points.length];
        if (distanceToSegment(point, points[index], next) <= edgeRadius) {
          return { trench, pointIndex: null };
        }
      }
      if (pointInPolygon(point, points)) {
        return { trench, pointIndex: null };
      }
      return null;
    }

    function findSelectedTrenchHit(point) {
      if (!selectedTrenchId) return null;
      const trench = (deployment.trenches || []).find((item) => item.id === selectedTrenchId);
      return trench ? trenchHit(trench, point, 22, 16) : null;
    }

    function findSelectedPlacement(point) {
      if (!selectedPlacementId) return null;
      const item = deployment.placements.find((entry) => entry.id === selectedPlacementId);
      if (!item) return null;
      const dx = point.x - item.x;
      const dy = point.y - item.y;
      return Math.sqrt(dx * dx + dy * dy) <= 24 ? item : null;
    }

    function updateTrenchButtons() {
      const drawBtn = document.getElementById("drawTrenchBtn");
      const cancelBtn = document.getElementById("cancelTrenchBtn");
      drawBtn.classList.toggle("active", drawingTrench);
      drawBtn.textContent = drawingTrench ? "Drawing " + trenchDraft.length + "/4" : "Draw trench";
      cancelBtn.disabled = !drawingTrench && trenchDraft.length === 0;
      mapHint.textContent = drawingTrench
        ? "Click four trench corners on the map."
        : "Click to choose a position, then add selected platform. Use Draw trench for 4-point trench areas.";
    }

    function startTrenchDrawing() {
      drawingTrench = true;
      trenchDraft = [];
      pendingPoint = null;
      selectedPlacementId = null;
      selectedTrenchId = null;
      updateTrenchButtons();
      renderDeployment();
    }

    function cancelTrenchDrawing() {
      drawingTrench = false;
      trenchDraft = [];
      updateTrenchButtons();
      renderDeployment();
    }

    function addTrenchPoint(point) {
      trenchDraft.push(clampMapPoint(point));
      if (trenchDraft.length < 4) {
        updateTrenchButtons();
        renderDeployment();
        return;
      }
      const trench = {
        id: "trench_" + Date.now(),
        points: trenchDraft.map(clampMapPoint),
      };
      deployment.trenches.push(trench);
      selectedPlacementId = null;
      selectedTrenchId = trench.id;
      drawingTrench = false;
      trenchDraft = [];
      updateTrenchButtons();
      renderDeployment();
      updatePreview();
    }

    function addPlacement(point) {
      const target = point || pendingPoint || { x: Math.round(canvas.width / 2), y: Math.round(canvas.height / 2) };
      const placement = {
        id: "placement_" + Date.now(),
        team: ids.teamSelect.value,
        unitType: ids.unitSelect.value,
        x: target.x,
        y: target.y,
        quantity: Math.max(1, Number(ids.quantityInput.value || 1)),
      };
      deployment.placements.push(placement);
      selectedPlacementId = placement.id;
      selectedTrenchId = null;
      pendingPoint = null;
      renderDeployment();
      updatePreview();
    }

    function choosePendingPoint(point) {
      pendingPoint = point;
      selectedPlacementId = null;
      selectedTrenchId = null;
      renderDeployment();
    }

    function deleteSelectedPlacement() {
      if (selectedPlacementId) {
        deployment.placements = deployment.placements.filter((item) => item.id !== selectedPlacementId);
        selectedPlacementId = null;
      } else if (selectedTrenchId) {
        deployment.trenches = deployment.trenches.filter((item) => item.id !== selectedTrenchId);
        selectedTrenchId = null;
      } else {
        return;
      }
      renderDeployment();
      updatePreview();
    }

    function teamColor(team) {
      return team === "RED" ? "#b83d4c" : "#2367d1";
    }

    function drawTrenchShape(trench, selected) {
      const points = trench.points || [];
      if (points.length !== 4) return;
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let index = 1; index < points.length; index += 1) {
        ctx.lineTo(points[index].x, points[index].y);
      }
      ctx.closePath();
      ctx.fillStyle = selected ? "rgba(168, 102, 17, 0.44)" : "rgba(168, 102, 17, 0.22)";
      ctx.fill();
      ctx.lineWidth = selected ? 5 : 2;
      ctx.strokeStyle = selected ? "#101820" : "#8a5a1c";
      ctx.stroke();

      const center = points.reduce((acc, point) => ({ x: acc.x + point.x / 4, y: acc.y + point.y / 4 }), { x: 0, y: 0 });
      ctx.fillStyle = "#101820";
      ctx.font = selected ? "900 13px Segoe UI, sans-serif" : "800 12px Segoe UI, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("TR", center.x, center.y);

      if (selected) {
        for (const point of points) {
          ctx.beginPath();
          ctx.arc(point.x, point.y, 10, 0, Math.PI * 2);
          ctx.fillStyle = "#ffffff";
          ctx.fill();
          ctx.lineWidth = 4;
          ctx.strokeStyle = "#101820";
          ctx.stroke();
        }
      }
    }

    function drawPlacementMarker(item, selected) {
      const color = teamColor(item.team);
      ctx.beginPath();
      ctx.arc(item.x, item.y, selected ? 15 : 10, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = selected ? 5 : 2;
      ctx.strokeStyle = selected ? "#101820" : "rgba(255,255,255,0.85)";
      ctx.stroke();
      if (selected) {
        ctx.beginPath();
        ctx.arc(item.x, item.y, 20, 0, Math.PI * 2);
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
      }

      ctx.font = "700 12px Segoe UI, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#ffffff";
      ctx.fillText(symbols[item.unitType] || item.unitType.slice(0, 2), item.x, item.y);

      if (item.quantity > 1) {
        ctx.fillStyle = "#101820";
        ctx.beginPath();
        ctx.arc(item.x + 13, item.y - 13, 9, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.font = "700 10px Segoe UI, sans-serif";
        ctx.fillText(String(item.quantity), item.x + 13, item.y - 13);
      }
    }

    function drawTrenchDraft() {
      if (trenchDraft.length === 0) return;
      ctx.beginPath();
      ctx.moveTo(trenchDraft[0].x, trenchDraft[0].y);
      for (let index = 1; index < trenchDraft.length; index += 1) {
        ctx.lineTo(trenchDraft[index].x, trenchDraft[index].y);
      }
      ctx.strokeStyle = "#101820";
      ctx.lineWidth = 3;
      ctx.setLineDash([8, 6]);
      ctx.stroke();
      ctx.setLineDash([]);
      for (const point of trenchDraft) {
        ctx.beginPath();
        ctx.arc(point.x, point.y, 7, 0, Math.PI * 2);
        ctx.fillStyle = "#a86611";
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
      }
    }

    function drawPendingPoint() {
      if (!pendingPoint) return;
      ctx.strokeStyle = "#101820";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(pendingPoint.x - 14, pendingPoint.y);
      ctx.lineTo(pendingPoint.x + 14, pendingPoint.y);
      ctx.moveTo(pendingPoint.x, pendingPoint.y - 14);
      ctx.lineTo(pendingPoint.x, pendingPoint.y + 14);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(pendingPoint.x, pendingPoint.y, 10, 0, Math.PI * 2);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.strokeStyle = "#101820";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    function drawMap() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (mapImage.complete && mapImage.naturalWidth > 0) {
        ctx.drawImage(mapImage, 0, 0, canvas.width, canvas.height);
      } else {
        ctx.fillStyle = "#eff4f8";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }

      for (const trench of deployment.trenches || []) {
        if (trench.id !== selectedTrenchId) drawTrenchShape(trench, false);
      }
      drawTrenchDraft();
      drawPendingPoint();
      for (const item of deployment.placements) {
        if (item.id !== selectedPlacementId) drawPlacementMarker(item, false);
      }

      const selectedTrench = (deployment.trenches || []).find((item) => item.id === selectedTrenchId);
      if (selectedTrench) drawTrenchShape(selectedTrench, true);
      const selectedPlacement = deployment.placements.find((item) => item.id === selectedPlacementId);
      if (selectedPlacement) drawPlacementMarker(selectedPlacement, true);
    }

    function renderDeployment() {
      drawMap();
      const totals = {};
      for (const item of deployment.placements) {
        const key = item.team + " " + item.unitType;
        totals[key] = (totals[key] || 0) + Number(item.quantity || 1);
      }
      const totalUnits = Object.values(totals).reduce((acc, value) => acc + value, 0);
      let suffix = pendingPoint ? " | pending (" + pendingPoint.x + ", " + pendingPoint.y + ")" : "";
      if (drawingTrench) suffix = " | trench points " + trenchDraft.length + "/4";
      const trenchCount = (deployment.trenches || []).length;
      deploymentStatus.textContent = deployment.placements.length + " anchors, " + totalUnits + " units, " + trenchCount + " trenches" + suffix;
      placementList.innerHTML = "";
      for (const trench of (deployment.trenches || []).slice(-20).reverse()) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "placement-item" + (trench.id === selectedTrenchId ? " active" : "");
        const first = trench.points && trench.points[0] ? trench.points[0] : { x: 0, y: 0 };
        row.innerHTML = "<span>Trench</span><span>4 pts @ (" + first.x + ", " + first.y + ")</span>";
        row.addEventListener("click", () => {
          selectedPlacementId = null;
          selectedTrenchId = trench.id;
          pendingPoint = null;
          renderDeployment();
        });
        placementList.appendChild(row);
      }
      for (const item of deployment.placements.slice(-40).reverse()) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "placement-item" + (item.id === selectedPlacementId ? " active" : "");
        row.innerHTML = "<span>" + item.team + " " + (symbols[item.unitType] || item.unitType) +
          " x" + item.quantity + "</span><span>(" + item.x + ", " + item.y + ")</span>";
        row.addEventListener("click", () => {
          selectedPlacementId = item.id;
          selectedTrenchId = null;
          renderDeployment();
        });
        placementList.appendChild(row);
      }
    }

    async function saveDeployment() {
      try {
        deployment.name = ids.deploymentName.value || "manual_deployment";
        const data = await api("/api/deployments", {
          method: "POST",
          body: JSON.stringify({ name: deployment.name, deployment }),
        });
        refreshDeploymentFiles(data.deployments || []);
        ids.deploymentFiles.value = data.file;
        updateLoadDeploymentButton();
        loadedDeploymentFile = data.file;
        setDeployment(data.deployment);
        deploymentStatus.textContent = "Saved " + data.file;
      } catch (err) {
        alert(err.message);
      }
    }

    async function loadSelectedDeployment() {
      const file = ids.deploymentFiles.value;
      if (!file) {
        deploymentStatus.textContent = "Choose a saved deployment first";
        updateLoadDeploymentButton();
        return;
      }
      try {
        const data = await api("/api/deployments/" + encodeURIComponent(file));
        setDeployment(data.deployment);
        loadedDeploymentFile = file;
        deploymentStatus.textContent = "Loaded " + file;
      } catch (err) {
        alert(err.message);
      }
    }

    function downloadDeployment() {
      const blob = new Blob([JSON.stringify(deployment, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (ids.deploymentName.value || "deployment") + ".json";
      a.click();
      URL.revokeObjectURL(url);
    }

    function timestampSuffix() {
      const now = new Date();
      const pad = (value) => String(value).padStart(2, "0");
      return now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) +
        "_" + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
    }

    async function saveDeploymentAsNew() {
      const baseName = ids.deploymentName.value || deployment.name || "manual_deployment";
      ids.deploymentName.value = baseName + "_" + timestampSuffix();
      await saveDeployment();
    }

    async function loadLocalDeployment() {
      const file = ids.deploymentUpload.files && ids.deploymentUpload.files[0];
      if (!file) {
        alert("Choose a deployment JSON file first.");
        return;
      }
      try {
        const text = await file.text();
        const nextDeployment = JSON.parse(text);
        setDeployment(nextDeployment);
        loadedDeploymentFile = "";
        deploymentStatus.textContent = "Loaded local file " + file.name;
      } catch (err) {
        alert(err.message);
      }
    }

    function setMapPanelHeight(value) {
      mapPanel.style.height = value + "px";
      window.localStorage.setItem("wargame.mapPanelHeight", String(value));
    }

    async function run() {
      runBtn.disabled = true;
      try {
        await api("/api/run", {
          method: "POST",
          body: JSON.stringify(payload()),
        });
        clearedAt = 0;
        await refreshStatus();
      } catch (err) {
        alert(err.message);
      } finally {
        runBtn.disabled = false;
      }
    }

    async function stop() {
      stopBtn.disabled = true;
      try {
        await api("/api/stop", { method: "POST", body: "{}" });
      } catch (err) {
        alert(err.message);
      }
    }

    function renderOutputs(items) {
      outputs.innerHTML = "";
      if (!items || items.length === 0) {
        const span = document.createElement("span");
        span.className = "subtle";
        span.textContent = "No copied outputs yet";
        outputs.appendChild(span);
        return;
      }
      for (const item of items) {
        const a = document.createElement("a");
        a.className = "chip";
        a.href = item.url;
        a.textContent = item.name + " (" + item.sizeLabel + ")";
        a.target = "_blank";
        outputs.appendChild(a);
      }
    }

    async function refreshStatus() {
      const tail = Math.max(100, Number(ids.logTail.value || 500));
      const data = await api("/api/status?tail=" + encodeURIComponent(tail));
      const run = data.run;
      const active = data.active;

      statusText.textContent = run ? run.status : "Idle";
      statusText.className = active ? "warn" : (run && run.exitCode === 0 ? "ok" : "");
      runId.textContent = run ? run.runId : "-";
      exitCode.textContent = run && run.exitCode !== null ? run.exitCode : "-";
      elapsed.textContent = run ? run.elapsedLabel : "-";
      runDir.textContent = run ? run.runDir : "No run yet";
      stopBtn.disabled = !active;
      runBtn.disabled = active;

      if (run && run.logs) {
        const visibleLogs = run.logs.slice(clearedAt);
        logText.textContent = visibleLogs.join("");
        const logBox = logText.parentElement;
        logBox.scrollTop = logBox.scrollHeight;
      }
      renderOutputs(run ? run.outputs : []);
    }

    for (const input of Object.values(ids)) {
      input.addEventListener("input", updatePreview);
      input.addEventListener("change", updatePreview);
    }
    ids.teamSelect.addEventListener("change", setQuantityFromSquad);
    ids.unitSelect.addEventListener("change", setQuantityFromSquad);
    ids.deploymentFiles.addEventListener("change", updateLoadDeploymentButton);
    ids.mapSelect.addEventListener("change", () => {
      deployment.mapPath = ids.mapSelect.value;
      deployment.mapWidth = 0;
      deployment.mapHeight = 0;
      deployment.placements = [];
      deployment.trenches = [];
      selectedPlacementId = null;
      selectedTrenchId = null;
      pendingPoint = null;
      drawingTrench = false;
      trenchDraft = [];
      loadedDeploymentFile = "";
      updateTrenchButtons();
      loadMapImage();
      renderDeployment();
      deploymentStatus.textContent = "Map selected; no deployment loaded";
      updatePreview();
    });
    document.querySelectorAll("[data-preset]").forEach((btn) => {
      btn.addEventListener("click", () => setPreset(btn.dataset.preset));
    });
    ids.mapHeightSlider.value = window.localStorage.getItem("wargame.mapPanelHeight") || ids.mapHeightSlider.value;
    setMapPanelHeight(Number(ids.mapHeightSlider.value));
    ids.mapHeightSlider.addEventListener("input", () => setMapPanelHeight(Number(ids.mapHeightSlider.value)));
    canvas.addEventListener("mousedown", (event) => {
      const point = canvasPoint(event);
      if (drawingTrench) {
        addTrenchPoint(point);
        return;
      }
      const selectedTrenchHit = findSelectedTrenchHit(point);
      if (selectedTrenchHit) {
        selectedPlacementId = null;
        selectedTrenchId = selectedTrenchHit.trench.id;
        dragTrench = {
          id: selectedTrenchHit.trench.id,
          pointIndex: selectedTrenchHit.pointIndex,
          lastPoint: point,
        };
        pendingPoint = null;
        renderDeployment();
        return;
      }
      const selectedPlacementHit = findSelectedPlacement(point);
      if (selectedPlacementHit) {
        selectedPlacementId = selectedPlacementHit.id;
        selectedTrenchId = null;
        dragPlacementId = selectedPlacementHit.id;
        pendingPoint = null;
        renderDeployment();
        return;
      }
      const hit = findPlacement(point);
      if (hit) {
        selectedPlacementId = hit.id;
        selectedTrenchId = null;
        dragPlacementId = hit.id;
        pendingPoint = null;
        renderDeployment();
        return;
      }
      const trenchHit = findTrenchHit(point);
      if (trenchHit) {
        selectedPlacementId = null;
        selectedTrenchId = trenchHit.trench.id;
        dragTrench = {
          id: trenchHit.trench.id,
          pointIndex: trenchHit.pointIndex,
          lastPoint: point,
        };
        pendingPoint = null;
        renderDeployment();
      } else {
        choosePendingPoint(point);
      }
    });
    canvas.addEventListener("mousemove", (event) => {
      const point = canvasPoint(event);
      mapCoords.textContent = "x: " + point.x + ", y: " + point.y;
      if (dragPlacementId) {
        const item = deployment.placements.find((entry) => entry.id === dragPlacementId);
        if (!item) return;
        item.x = point.x;
        item.y = point.y;
        renderDeployment();
        updatePreview();
        return;
      }
      if (dragTrench) {
        const trench = (deployment.trenches || []).find((entry) => entry.id === dragTrench.id);
        if (!trench) return;
        if (dragTrench.pointIndex !== null) {
          trench.points[dragTrench.pointIndex] = clampMapPoint(point);
        } else {
          const dx = point.x - dragTrench.lastPoint.x;
          const dy = point.y - dragTrench.lastPoint.y;
          trench.points = trench.points.map((corner) => clampMapPoint({ x: corner.x + dx, y: corner.y + dy }));
          dragTrench.lastPoint = point;
        }
        renderDeployment();
        updatePreview();
      }
    });
    window.addEventListener("mouseup", () => {
      dragPlacementId = null;
      dragTrench = null;
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Delete" || event.key === "Backspace") {
        const tag = document.activeElement && document.activeElement.tagName;
        if (tag !== "INPUT" && tag !== "SELECT") {
          deleteSelectedPlacement();
        }
      }
    });
    runBtn.addEventListener("click", run);
    stopBtn.addEventListener("click", stop);
    document.getElementById("addSelectedBtn").addEventListener("click", () => addPlacement());
    document.getElementById("drawTrenchBtn").addEventListener("click", startTrenchDrawing);
    document.getElementById("cancelTrenchBtn").addEventListener("click", cancelTrenchDrawing);
    document.getElementById("clearDeploymentBtn").addEventListener("click", () => {
      deployment.placements = [];
      deployment.trenches = [];
      selectedPlacementId = null;
      selectedTrenchId = null;
      pendingPoint = null;
      drawingTrench = false;
      trenchDraft = [];
      loadedDeploymentFile = "";
      updateTrenchButtons();
      renderDeployment();
      updatePreview();
    });
    document.getElementById("deletePlacementBtn").addEventListener("click", deleteSelectedPlacement);
    document.getElementById("saveDeploymentBtn").addEventListener("click", saveDeployment);
    document.getElementById("saveAsDeploymentBtn").addEventListener("click", saveDeploymentAsNew);
    document.getElementById("loadDeploymentBtn").addEventListener("click", loadSelectedDeployment);
    document.getElementById("loadLocalDeploymentBtn").addEventListener("click", loadLocalDeployment);
    document.getElementById("downloadDeploymentBtn").addEventListener("click", downloadDeployment);
    document.getElementById("clearLogBtn").addEventListener("click", () => {
      const current = logText.textContent || "";
      clearedAt += current.split(/(?<=\n)/).filter(Boolean).length;
      logText.textContent = "";
    });

    updatePreview();
    updateTrenchButtons();
    updateLoadDeploymentButton();
    loadDefaults();
    loadDeploymentDefaults();
    refreshStatus();
    setInterval(refreshStatus, 1000);
  </script>
</body>
</html>
"""


@dataclass
class RunRecord:
    run_id: str
    run_dir: Path
    work_dir: Path
    command: List[str]
    started_at: float
    process: subprocess.Popen
    status: str = "running"
    exit_code: Optional[int] = None
    stopped_by_user: bool = False
    finished_at: Optional[float] = None
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=LOG_TAIL_LIMIT))
    outputs: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)


class LauncherState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current: Optional[RunRecord] = None
        self.last: Optional[RunRecord] = None


STATE = LauncherState()


def load_config() -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed. Install dependencies from requirements.txt.")
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Missing config file: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def config_path(value: Optional[str], base_dir: Path = PROJECT_DIR) -> Optional[Path]:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path


def safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    cleaned = cleaned.strip("_")
    return cleaned or datetime.now().strftime("deployment_%Y%m%d_%H%M%S")


def deployment_file(name: str) -> Path:
    return DEPLOYMENTS_DIR / f"{safe_name(name)}.json"


def list_maps(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen = set()
    maps: List[Dict[str, Any]] = []
    configured = cfg.get("simulation", {}).get("background_image_path")
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend(str(path.relative_to(PROJECT_DIR)).replace("\\", "/") for path in (PROJECT_DIR / "database").glob("*.png"))
    for rel in candidates:
        normalized = str(rel).replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        path = config_path(normalized)
        maps.append(
            {
                "path": normalized,
                "name": Path(normalized).name,
                "exists": bool(path and path.exists()),
                "url": f"/assets/{normalized}",
            }
        )
    return maps


def deployment_from_config(cfg: Dict[str, Any], name: str = "current_config") -> Dict[str, Any]:
    sim_cfg = cfg.get("simulation", {})
    positions_cfg = cfg.get("initial_positions", {})
    counts: Dict[str, int] = {}
    placements: List[Dict[str, Any]] = []

    for team in ("RED", "BLUE"):
        for unit_type in UNIT_TYPES:
            positions = positions_cfg.get(team, {}).get(unit_type, []) or []
            count_key = COUNT_KEYS.get((team, unit_type))
            count = int(cfg.get(count_key, len(positions))) if count_key else len(positions)
            counts[f"{team}.{unit_type}"] = count
            clipped = positions[:count]
            grouped: Dict[tuple[int, int], int] = {}
            for pos in clipped:
                if not isinstance(pos, list) or len(pos) < 2:
                    continue
                key = (int(round(pos[0])), int(round(pos[1])))
                grouped[key] = grouped.get(key, 0) + 1
            for (x, y), quantity in grouped.items():
                placements.append(
                    {
                        "id": f"{team}_{unit_type}_{len(placements) + 1}",
                        "team": team,
                        "unitType": unit_type,
                        "x": x,
                        "y": y,
                        "quantity": quantity,
                    }
                )

    return {
        "version": 1,
        "name": name,
        "mapPath": sim_cfg.get("background_image_path", "database/background_5x.png"),
        "mapWidth": int(sim_cfg.get("map_width_px", 1200)),
        "mapHeight": int(sim_cfg.get("map_height_px", 875)),
        "placements": placements,
        "trenches": [],
        "counts": counts,
    }


def normalize_deployment(raw: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    base = deployment_from_config(cfg, "deployment")
    deployment = {
        "version": int(raw.get("version", 1)),
        "name": str(raw.get("name") or base["name"]),
        "mapPath": str(raw.get("mapPath") or base["mapPath"]),
        "mapWidth": int(raw.get("mapWidth") or base["mapWidth"]),
        "mapHeight": int(raw.get("mapHeight") or base["mapHeight"]),
        "placements": [],
        "trenches": [],
    }
    for index, placement in enumerate(raw.get("placements", []) or []):
        team = str(placement.get("team", "")).upper()
        unit_type = str(placement.get("unitType", "")).upper()
        if team not in ("RED", "BLUE") or unit_type not in UNIT_TYPES:
            continue
        x = int(round(float(placement.get("x", 0))))
        y = int(round(float(placement.get("y", 0))))
        quantity = max(1, int(round(float(placement.get("quantity", 1)))))
        deployment["placements"].append(
            {
                "id": str(placement.get("id") or f"{team}_{unit_type}_{index + 1}"),
                "team": team,
                "unitType": unit_type,
                "x": max(0, min(deployment["mapWidth"], x)),
                "y": max(0, min(deployment["mapHeight"], y)),
                "quantity": quantity,
            }
        )
    for index, trench in enumerate(raw.get("trenches", []) or []):
        raw_points = trench.get("points", [])
        if not isinstance(raw_points, list) or len(raw_points) != 4:
            continue
        points = []
        for point in raw_points:
            if isinstance(point, list) and len(point) >= 2:
                x_raw, y_raw = point[0], point[1]
            elif isinstance(point, dict):
                x_raw, y_raw = point.get("x", 0), point.get("y", 0)
            else:
                points = []
                break
            x = int(round(float(x_raw)))
            y = int(round(float(y_raw)))
            points.append(
                {
                    "x": max(0, min(deployment["mapWidth"], x)),
                    "y": max(0, min(deployment["mapHeight"], y)),
                }
            )
        if len(points) != 4:
            continue
        deployment["trenches"].append(
            {
                "id": str(trench.get("id") or f"TRENCH_{index + 1}"),
                "points": points,
            }
        )
    return deployment


def apply_deployment_to_config(cfg: Dict[str, Any], deployment: Dict[str, Any]) -> Dict[str, Any]:
    deployment = normalize_deployment(deployment, cfg)
    cfg = dict(cfg)
    cfg["simulation"] = dict(cfg.get("simulation", {}))
    cfg["simulation"]["background_image_path"] = deployment["mapPath"]
    cfg["simulation"]["map_width_px"] = deployment["mapWidth"]
    cfg["simulation"]["map_height_px"] = deployment["mapHeight"]
    cfg["initial_positions"] = {
        "RED": {unit_type: [] for unit_type in UNIT_TYPES},
        "BLUE": {unit_type: [] for unit_type in UNIT_TYPES},
    }
    counts: Dict[tuple[str, str], int] = {(team, unit_type): 0 for team in ("RED", "BLUE") for unit_type in UNIT_TYPES}

    for placement in deployment["placements"]:
        team = placement["team"]
        unit_type = placement["unitType"]
        quantity = int(placement["quantity"])
        position = [int(placement["x"]), int(placement["y"])]
        cfg["initial_positions"][team][unit_type].extend([position[:] for _ in range(quantity)])
        counts[(team, unit_type)] += quantity

    for key, count_key in COUNT_KEYS.items():
        cfg[count_key] = counts.get(key, 0)

    return cfg


def point_in_polygon(x: float, y: float, points: List[Dict[str, int]]) -> bool:
    inside = False
    count = len(points)
    for i in range(count):
        j = (i - 1) % count
        xi, yi = points[i]["x"], points[i]["y"]
        xj, yj = points[j]["x"], points[j]["y"]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / ((yj - yi) or 1) + xi
            if x < x_intersect:
                inside = not inside
    return inside


def write_trench_mask(deployment: Dict[str, Any], output_path: Path) -> Optional[Path]:
    trenches = deployment.get("trenches") or []
    if not trenches:
        return None

    width = max(1, int(deployment.get("mapWidth") or 1200))
    height = max(1, int(deployment.get("mapHeight") or 875))
    mask = [bytearray(width) for _ in range(height)]

    for trench in trenches:
        points = trench.get("points") or []
        if len(points) != 4:
            continue
        min_x = max(0, min(point["x"] for point in points))
        max_x = min(width - 1, max(point["x"] for point in points))
        min_y = max(0, min(point["y"] for point in points))
        max_y = min(height - 1, max(point["y"] for point in points))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if point_in_polygon(x + 0.5, y + 0.5, points):
                    mask[y][x] = 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        for row in mask:
            handle.write(",".join("1" if value else "0" for value in row))
            handle.write("\n")
    return output_path


def list_deployments() -> List[Dict[str, Any]]:
    DEPLOYMENTS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(DEPLOYMENTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        items.append(
            {
                "file": path.name,
                "name": data.get("name") or path.stem,
                "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return items


def load_deployment_file(filename: str) -> Dict[str, Any]:
    safe = Path(filename).name
    path = (DEPLOYMENTS_DIR / safe).resolve()
    root = DEPLOYMENTS_DIR.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise RuntimeError("Invalid deployment path.")
    if path.suffix.lower() != ".json" or not path.exists():
        raise RuntimeError("Deployment file not found.")
    return normalize_deployment(json.loads(path.read_text(encoding="utf-8")))


def size_label(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def make_run_dir() -> tuple[str, Path]:
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    for index in range(100):
        run_id = base if index == 0 else f"{base}_{index:02d}"
        run_dir = RUNS_DIR / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_id, run_dir
        except FileExistsError:
            continue
    raise RuntimeError("Could not create a unique run directory.")


def validate_float(payload: Dict[str, Any], key: str, default: float, minimum: float) -> float:
    raw = payload.get(key, default)
    if raw is None or raw == "":
        value = default
    else:
        value = float(raw)
    if value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return value


def build_command(payload: Dict[str, Any]) -> List[str]:
    time_scale = validate_float(payload, "timeScale", 5.0, 0.1)
    sim_speed = validate_float(payload, "simSpeed", 1.0, 0.1)
    max_time_raw = payload.get("maxTime")

    command = [
        sys.executable,
        "simulation.py",
        "--time-scale",
        f"{time_scale:g}",
        "--sim_speed",
        f"{sim_speed:g}",
        "--detection",
        "T" if payload.get("showDetection") else "F",
        "--eligible_TL",
        "T" if payload.get("showEligibleTargets") else "F",
        "--fire",
        "T" if payload.get("showFire") else "F",
    ]

    if max_time_raw not in (None, ""):
        max_time = float(max_time_raw)
        if max_time <= 0:
            raise ValueError("maxTime must be greater than 0")
        command.extend(["--max-time", f"{max_time:g}"])

    if payload.get("noHold"):
        command.append("--no-hold")
    if payload.get("noVideo"):
        command.append("--no-video")
    return command


def command_display(command: List[str]) -> str:
    return subprocess.list2cmdline(command)


def link_or_copy_dir(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    try:
        os.symlink(source, destination, target_is_directory=True)
        return
    except OSError:
        pass
    if os.name == "nt":
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.CalledProcessError):
            pass
    shutil.copytree(source, destination)


def prepare_run_workspace(payload: Dict[str, Any], run_dir: Path) -> Path:
    cfg = load_config()
    deployment = None
    work_dir = run_dir / "workspace"
    work_dir.mkdir(parents=True, exist_ok=True)

    deployment = payload.get("deployment")
    if payload.get("useDeployment") and isinstance(deployment, dict):
        deployment = normalize_deployment(deployment, cfg)
        cfg = apply_deployment_to_config(cfg, deployment)
        (run_dir / "deployment.applied.json").write_text(
            json.dumps(deployment, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        deployment = None

    shutil.copy2(PROJECT_DIR / "simulation.py", work_dir / "simulation.py")
    for top_level_file in ("Damage_logics.csv",):
        source = PROJECT_DIR / top_level_file
        if source.exists():
            shutil.copy2(source, work_dir / top_level_file)
    for folder in ("model", "database"):
        link_or_copy_dir(PROJECT_DIR / folder, work_dir / folder)
    (work_dir / "results").mkdir(exist_ok=True)
    if deployment and deployment.get("trenches"):
        trench_mask = write_trench_mask(deployment, work_dir / "launcher_trench_mask.csv")
        if trench_mask:
            cfg["terrain"] = dict(cfg.get("terrain", {}))
            cfg["terrain"]["trench_mask_file"] = trench_mask.name
    (work_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return work_dir


def append_log(record: RunRecord, text: str) -> None:
    with STATE.lock:
        record.logs.append(text)
    with (record.run_dir / "stdout.log").open("a", encoding="utf-8", errors="replace") as log_file:
        log_file.write(text)


def collect_outputs(record: RunRecord) -> None:
    try:
        config_file = record.work_dir / "config.yaml"
        with config_file.open("r", encoding="utf-8") as handle:
            cfg = yaml.safe_load(handle) or {}
    except Exception as exc:
        append_log(record, f"[launcher] Could not read output paths: {exc}\n")
        cfg = {}

    candidates = [
        config_path(cfg.get("csv", {}).get("output_path", "results/simulation.csv"), record.work_dir),
        config_path(cfg.get("csv", {}).get("money_output_path", "results/money.csv"), record.work_dir),
        config_path(cfg.get("video", {}).get("output_path", "results/simulation.mp4"), record.work_dir),
    ]

    copied: List[Dict[str, Any]] = []
    for source in candidates:
        if source is None or not source.exists() or not source.is_file():
            continue
        source_stat = source.stat()
        if source_stat.st_mtime < record.started_at - 1.0:
            append_log(record, f"[launcher] Skipped stale output: {source}\n")
            continue
        destination = record.run_dir / source.name
        try:
            shutil.copy2(source, destination)
            stat = destination.stat()
            copied.append(
                {
                    "name": destination.name,
                    "size": stat.st_size,
                    "sizeLabel": size_label(stat.st_size),
                    "url": f"/runs/{record.run_id}/{destination.name}",
                }
            )
        except OSError as exc:
            append_log(record, f"[launcher] Failed to copy {source}: {exc}\n")

    log_path = record.run_dir / "stdout.log"
    if log_path.exists():
        stat = log_path.stat()
        copied.insert(
            0,
            {
                "name": "stdout.log",
                "size": stat.st_size,
                "sizeLabel": size_label(stat.st_size),
                "url": f"/runs/{record.run_id}/stdout.log",
            },
        )

    command_path = record.run_dir / "command.txt"
    if command_path.exists():
        stat = command_path.stat()
        copied.insert(
            1,
            {
                "name": "command.txt",
                "size": stat.st_size,
                "sizeLabel": size_label(stat.st_size),
                "url": f"/runs/{record.run_id}/command.txt",
            },
        )

    generated_config = record.work_dir / "config.yaml"
    if generated_config.exists():
        stat = generated_config.stat()
        copied.insert(
            2,
            {
                "name": "generated-config.yaml",
                "size": stat.st_size,
                "sizeLabel": size_label(stat.st_size),
                "url": f"/runs/{record.run_id}/workspace/config.yaml",
            },
        )

    applied_deployment = record.run_dir / "deployment.applied.json"
    if applied_deployment.exists():
        stat = applied_deployment.stat()
        copied.insert(
            3,
            {
                "name": "deployment.applied.json",
                "size": stat.st_size,
                "sizeLabel": size_label(stat.st_size),
                "url": f"/runs/{record.run_id}/deployment.applied.json",
            },
        )

    with STATE.lock:
        record.outputs = copied


def run_reader(record: RunRecord) -> None:
    try:
        assert record.process.stdout is not None
        for line in record.process.stdout:
            append_log(record, line)
        exit_code = record.process.wait()
    except Exception as exc:
        exit_code = -1
        append_log(record, f"[launcher] Log reader failed: {exc}\n")

    with STATE.lock:
        record.exit_code = exit_code
        record.finished_at = time.time()
        if record.stopped_by_user:
            record.status = "stopped"
        elif exit_code == 0:
            record.status = "finished"
        else:
            record.status = "failed"

    collect_outputs(record)

    with STATE.lock:
        if STATE.current is record:
            STATE.current = None
        STATE.last = record


def start_run(payload: Dict[str, Any]) -> RunRecord:
    command = build_command(payload)
    run_id, run_dir = make_run_dir()
    work_dir = prepare_run_workspace(payload, run_dir)

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, run_dir / "config.snapshot.yaml")
    (run_dir / "command.txt").write_text(command_display(command) + "\n", encoding="utf-8")
    (run_dir / "request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        command,
        cwd=str(work_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    record = RunRecord(
        run_id=run_id,
        run_dir=run_dir,
        work_dir=work_dir,
        command=command,
        started_at=time.time(),
        process=process,
    )
    append_log(record, f"[launcher] Started {command_display(command)}\n")
    append_log(record, f"[launcher] Run folder: {run_dir}\n")

    thread = threading.Thread(target=run_reader, args=(record,), daemon=True)
    thread.start()
    return record


def stop_current_run() -> bool:
    with STATE.lock:
        record = STATE.current
        if record is None:
            return False
        record.stopped_by_user = True
        process = record.process

    append_log(record, "[launcher] Stop requested.\n")
    process.terminate()

    def force_kill() -> None:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            append_log(record, "[launcher] Process did not exit; killing it.\n")
            process.kill()

    threading.Thread(target=force_kill, daemon=True).start()
    return True


def serialize_run(record: Optional[RunRecord], tail: int) -> Optional[Dict[str, Any]]:
    if record is None:
        return None
    with STATE.lock:
        logs = list(record.logs)[-tail:]
        outputs = list(record.outputs)
        exit_code = record.exit_code
        status = record.status
    elapsed = record.elapsed_seconds
    if elapsed < 60:
        elapsed_label = f"{elapsed:.0f}s"
    else:
        elapsed_label = f"{elapsed / 60:.1f}m"
    return {
        "runId": record.run_id,
        "runDir": str(record.run_dir),
        "command": command_display(record.command),
        "status": status,
        "exitCode": exit_code,
        "elapsedSeconds": elapsed,
        "elapsedLabel": elapsed_label,
        "logs": logs,
        "outputs": outputs,
    }


class LauncherHandler(BaseHTTPRequestHandler):
    server_version = "WargameLauncher/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[launcher] " + fmt % args + "\n")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(INDEX_HTML)
            return
        if parsed.path == "/api/defaults":
            self.handle_defaults()
            return
        if parsed.path == "/api/deployment":
            self.handle_deployment_defaults()
            return
        if parsed.path == "/api/deployments":
            self.handle_deployments()
            return
        if parsed.path.startswith("/api/deployments/"):
            self.handle_get_deployment(parsed.path)
            return
        if parsed.path == "/api/status":
            self.handle_status(parsed.query)
            return
        if parsed.path.startswith("/assets/"):
            self.handle_asset_file(parsed.path)
            return
        if parsed.path.startswith("/runs/"):
            self.handle_run_file(parsed.path)
            return
        self.send_error_json(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            self.handle_run()
            return
        if parsed.path == "/api/stop":
            self.handle_stop()
            return
        if parsed.path == "/api/deployments":
            self.handle_save_deployment()
            return
        self.send_error_json(404, "Not found")

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, body: Dict[str, Any], status: int = 200) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def handle_defaults(self) -> None:
        try:
            cfg = load_config()
            self.send_json(
                {
                    "projectDir": str(PROJECT_DIR),
                    "configPath": str(CONFIG_PATH),
                    "config": {
                        "maxTime": cfg.get("max_time"),
                        "videoEnabled": cfg.get("video", {}).get("enabled"),
                        "videoOutput": cfg.get("video", {}).get("output_path"),
                        "videoFps": cfg.get("video", {}).get("fps"),
                        "csvEnabled": cfg.get("csv", {}).get("enabled"),
                        "csvOutput": cfg.get("csv", {}).get("output_path"),
                        "moneyOutput": cfg.get("csv", {}).get("money_output_path"),
                    },
                }
            )
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def handle_deployment_defaults(self) -> None:
        try:
            cfg = load_config()
            platform_cfg = cfg.get("platform_overrides", {})
            platforms = {
                team: {
                    unit_type: {
                        **(cfg.get("units", {}).get(unit_type, {}) or {}),
                        **(platform_cfg.get(team, {}).get(unit_type, {}) or {}),
                        **(cfg.get("unit_overrides", {}).get(team, {}).get(unit_type, {}) or {}),
                        "symbol": SYMBOLS[unit_type],
                    }
                    for unit_type in UNIT_TYPES
                }
                for team in ("RED", "BLUE")
            }
            self.send_json(
                {
                    "maps": list_maps(cfg),
                    "unitTypes": UNIT_TYPES,
                    "symbols": SYMBOLS,
                    "squadSizes": cfg.get("squad_sizes", {}),
                    "platforms": platforms,
                    "deployment": deployment_from_config(cfg),
                    "deployments": list_deployments(),
                }
            )
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def handle_deployments(self) -> None:
        try:
            self.send_json({"deployments": list_deployments()})
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def handle_get_deployment(self, path: str) -> None:
        try:
            filename = unquote(path[len("/api/deployments/") :])
            self.send_json({"deployment": load_deployment_file(filename)})
        except Exception as exc:
            self.send_error_json(404, str(exc))

    def handle_save_deployment(self) -> None:
        try:
            payload = self.read_json()
            name = safe_name(str(payload.get("name") or "deployment"))
            deployment = normalize_deployment(payload.get("deployment") or {})
            deployment["name"] = name
            DEPLOYMENTS_DIR.mkdir(parents=True, exist_ok=True)
            path = deployment_file(name)
            path.write_text(json.dumps(deployment, indent=2, ensure_ascii=False), encoding="utf-8")
            self.send_json(
                {
                    "ok": True,
                    "file": path.name,
                    "deployment": deployment,
                    "deployments": list_deployments(),
                }
            )
        except Exception as exc:
            self.send_error_json(400, str(exc))

    def handle_status(self, query: str) -> None:
        tail = 500
        for part in query.split("&"):
            if part.startswith("tail="):
                try:
                    tail = max(100, min(LOG_TAIL_LIMIT, int(part.split("=", 1)[1])))
                except ValueError:
                    tail = 500
        with STATE.lock:
            active = STATE.current is not None
            record = STATE.current or STATE.last
        self.send_json({"active": active, "run": serialize_run(record, tail)})

    def handle_run(self) -> None:
        try:
            payload = self.read_json()
            with STATE.lock:
                if STATE.current is not None:
                    self.send_error_json(409, "A simulation is already running.")
                    return
            record = start_run(payload)
            with STATE.lock:
                STATE.current = record
                STATE.last = record
            self.send_json({"ok": True, "run": serialize_run(record, 200)})
        except Exception as exc:
            self.send_error_json(400, str(exc))

    def handle_stop(self) -> None:
        if stop_current_run():
            self.send_json({"ok": True})
        else:
            self.send_error_json(409, "No active simulation.")

    def send_file(self, target: Path, root: Path) -> None:
        target = target.resolve()
        root = root.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self.send_error_json(403, "Invalid file path.")
            return
        if not target.exists() or not target.is_file():
            self.send_error_json(404, "File not found.")
            return

        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)

    def handle_asset_file(self, path: str) -> None:
        safe_suffix = unquote(path[len("/assets/") :]).replace("\\", "/")
        self.send_file(PROJECT_DIR / safe_suffix, PROJECT_DIR)

    def handle_run_file(self, path: str) -> None:
        safe_suffix = unquote(path[len("/runs/") :]).replace("\\", "/")
        self.send_file(RUNS_DIR / safe_suffix, RUNS_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the war-game web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    DEPLOYMENTS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), LauncherHandler)
    url = f"http://{args.host}:{server.server_port}/"
    print(f"War Game Launcher running at {url}")
    print(f"Project directory: {PROJECT_DIR}")
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping launcher...")
    finally:
        with STATE.lock:
            record = STATE.current
        if record is not None:
            stop_current_run()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
