from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request


app = Flask(__name__)


# ============================================================
# Support Types
# Restricting to fixed and roller only, based on your support
# reference but removing spring, hinged and free from the UI/API.
# ============================================================

class SupportType(Enum):
    FIXED = "fixed"
    ROLLER = "roller"


# ============================================================
# Core object model
# Based on your Beam / SteelMaterial / SteelSection structure.
# ============================================================

@dataclass
class SteelMaterial:
    id: str
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    region_availability: List[str] = field(default_factory=list)

    def get_property(self, key: str) -> Any:
        return self.properties.get(key)

    def set_properties(self, prop_key: str, prop_value: Any) -> "SteelMaterial":
        prop_map = {
            "fy": ["fy_40", "fy_80"],
            "fu": ["fu_40", "fu_80"],
            "fe": ["fe"],
        }

        if prop_key in prop_map:
            for mapped_key in prop_map[prop_key]:
                self.properties[mapped_key] = prop_value
        else:
            self.properties[prop_key] = prop_value

        return self


@dataclass
class SectionGeometry:
    h: float
    b: float
    tw: float
    tf: float
    r: float = 0.0


@dataclass
class SectionProperties:
    A: float
    Iy: float
    Iz: float
    Wy: float
    Wz: float
    Wply: float
    Wely: float
    It: float
    Iw: float
    mass_per_m: float


@dataclass
class SteelSection:
    name: str
    geometry: SectionGeometry
    properties: SectionProperties


@dataclass
class Beam:
    id: str
    length_m: float
    material: SteelMaterial
    section: SteelSection

    @property
    def EA(self) -> float:
        """
        Axial stiffness EA in N.
        E: N/mm²
        A: mm²
        """
        return self.material.get_property("fe") * self.section.properties.A

    @property
    def EI(self) -> float:
        """
        Bending stiffness EI in N·mm².
        E: N/mm²
        Iy: mm⁴
        """
        return self.material.get_property("fe") * self.section.properties.Iy


@dataclass
class UniformLoad:
    value_kn_m: float
    load_type: str = "service"


@dataclass
class AnalysisResult:
    beam_id: str
    load_combination: str
    properties: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# Python-based database
# Steel material and section database.
# Values are representative for demo/design workflow.
# Units:
# E, G, fy, fu: N/mm²
# Dimensions: mm
# Area: mm²
# I: mm⁴
# W: mm³
# ============================================================

STEEL_MATERIALS: Dict[str, SteelMaterial] = {
    "S275": SteelMaterial(
        id="S275",
        name="S275",
        properties={
            "ft": 0.0,
            "fu_40": 430.0,
            "fy_40": 275.0,
            "fu_80": 410.0,
            "fy_80": 255.0,
            "fu": 430.0,
            "fy": 275.0,
            "fe": 210000.0,
            "G": 81000.0,
            "nu": 0.30,
            "ksp": None,
            "phi": None,
        },
        region_availability=["EU"],
    ),
    "S355": SteelMaterial(
        id="S355",
        name="S355",
        properties={
            "ft": 0.0,
            "fu_40": 510.0,
            "fy_40": 355.0,
            "fu_80": 470.0,
            "fy_80": 335.0,
            "fu": 510.0,
            "fy": 355.0,
            "fe": 210000.0,
            "G": 81000.0,
            "nu": 0.30,
            "ksp": None,
            "phi": None,
        },
        region_availability=["EU"],
    ),
}


STEEL_SECTIONS: Dict[str, SteelSection] = {
    "IPE 200": SteelSection(
        name="IPE 200",
        geometry=SectionGeometry(h=200.0, b=100.0, tw=5.6, tf=8.5, r=12.0),
        properties=SectionProperties(
            A=2850.0,
            Iy=1943e4,
            Iz=142e4,
            Wy=194e3,
            Wz=28.5e3,
            Wply=221e3,
            Wely=194e3,
            It=6.98e4,
            Iw=12990e6,
            mass_per_m=22.4,
        ),
    ),
    "IPE 300": SteelSection(
        name="IPE 300",
        geometry=SectionGeometry(h=300.0, b=150.0, tw=7.1, tf=10.7, r=15.0),
        properties=SectionProperties(
            A=5381.0,
            Iy=8356e4,
            Iz=604e4,
            Wy=557e3,
            Wz=80.5e3,
            Wply=628e3,
            Wely=557e3,
            It=20.1e4,
            Iw=125900e6,
            mass_per_m=42.2,
        ),
    ),
    "IPE 400": SteelSection(
        name="IPE 400",
        geometry=SectionGeometry(h=400.0, b=180.0, tw=8.6, tf=13.5, r=21.0),
        properties=SectionProperties(
            A=8446.0,
            Iy=23130e4,
            Iz=1318e4,
            Wy=1156e3,
            Wz=146e3,
            Wply=1307e3,
            Wely=1156e3,
            It=51.1e4,
            Iw=490000e6,
            mass_per_m=66.3,
        ),
    ),
}


# ============================================================
# Properties module
# Shows all selected section/material/calculated properties.
# ============================================================

def get_beam_properties(beam: Beam) -> Dict[str, Any]:
    mat = beam.material
    sec = beam.section
    geo = sec.geometry
    props = sec.properties

    return {
        "beam": {
            "id": beam.id,
            "length_m": beam.length_m,
            "EA_N": beam.EA,
            "EI_Nmm2": beam.EI,
        },
        "material": {
            "id": mat.id,
            "name": mat.name,
            "fy_N_mm2": mat.get_property("fy"),
            "fu_N_mm2": mat.get_property("fu"),
            "E_N_mm2": mat.get_property("fe"),
            "G_N_mm2": mat.get_property("G"),
            "nu": mat.get_property("nu"),
        },
        "geometry": asdict(geo),
        "section_properties": asdict(props),
    }


# ============================================================
# Simple analysis module
# Uniform load, simply supported beam only.
#
# Coordinate:
# x = 0 at left support
# x = L at right support
#
# UDL over full beam only.
#
# Units:
# L: m and mm
# w: kN/m = N/mm
# V: kN
# M: kNm
# deflection: mm
# ============================================================

def analyze_simply_supported_udl(
    beam: Beam,
    w_kn_m: float,
    points: int = 121,
) -> Dict[str, Any]:
    if beam.length_m <= 0:
        raise ValueError("Beam length must be greater than zero.")

    if w_kn_m < 0:
        raise ValueError("Uniform load must be positive downward load.")

    L_m = beam.length_m
    L_mm = L_m * 1000.0
    EI = beam.EI

    if EI <= 0:
        raise ValueError("EI must be greater than zero.")

    # Since 1 kN/m = 1 N/mm
    w_n_mm = w_kn_m

    reaction_kn = w_kn_m * L_m / 2.0
    max_shear_kn = reaction_kn
    max_moment_knm = w_kn_m * L_m ** 2 / 8.0
    max_deflection_mm = 5.0 * w_n_mm * L_mm ** 4 / (384.0 * EI)

    x_m: List[float] = []
    shear_kn: List[float] = []
    moment_knm: List[float] = []
    deflection_mm: List[float] = []

    for i in range(points):
        x = L_m * i / (points - 1)
        x_mm = x * 1000.0

        V = reaction_kn - w_kn_m * x
        M = reaction_kn * x - w_kn_m * x ** 2 / 2.0

        # Downward deflection positive for chart readability.
        delta = (
            w_n_mm
            * x_mm
            * (L_mm ** 3 - 2.0 * L_mm * x_mm ** 2 + x_mm ** 3)
            / (24.0 * EI)
        )

        x_m.append(round(x, 4))
        shear_kn.append(round(V, 4))
        moment_knm.append(round(M, 4))
        deflection_mm.append(round(delta, 6))

    return {
        "assumption": "Simply supported single-span beam with full-span uniform load.",
        "reactions": {
            "left_R_A_kN": reaction_kn,
            "right_R_B_kN": reaction_kn,
        },
        "maxima": {
            "max_shear_kN": max_shear_kn,
            "max_moment_kNm": max_moment_knm,
            "max_deflection_mm": max_deflection_mm,
            "deflection_limit_L_over_250_mm": L_mm / 250.0,
            "deflection_utilisation": max_deflection_mm / (L_mm / 250.0),
        },
        "diagrams": {
            "x_m": x_m,
            "shear_kN": shear_kn,
            "moment_kNm": moment_knm,
            "deflection_mm": deflection_mm,
        },
    }


# ============================================================
# Design module
# Based on your ULS design reference.
# Includes:
# 1. ULS actions
# 2. Section classification
# 3. Bending resistance
# 4. Shear resistance
# 5. LTB
# 6. Web bearing
# ============================================================

def classify_section(section: SteelSection, fy: float) -> Dict[str, Any]:
    geo = section.geometry

    eps = math.sqrt(235.0 / fy)

    c_web = geo.h - 2.0 * geo.tf - 2.0 * geo.r
    web_ratio = c_web / geo.tw

    if web_ratio <= 72.0 * eps:
        web_cls = 1
    elif web_ratio <= 83.0 * eps:
        web_cls = 2
    elif web_ratio <= 124.0 * eps:
        web_cls = 3
    else:
        web_cls = 4

    c_flange = (geo.b - geo.tw - 2.0 * geo.r) / 2.0
    flange_ratio = c_flange / geo.tf

    if flange_ratio <= 9.0 * eps:
        flange_cls = 1
    elif flange_ratio <= 10.0 * eps:
        flange_cls = 2
    elif flange_ratio <= 14.0 * eps:
        flange_cls = 3
    else:
        flange_cls = 4

    return {
        "epsilon": eps,
        "web_c_mm": c_web,
        "web_c_over_t": web_ratio,
        "web_class": web_cls,
        "flange_c_mm": c_flange,
        "flange_c_over_t": flange_ratio,
        "flange_class": flange_cls,
        "section_class": max(web_cls, flange_cls),
    }


def design_bending_resistance(
    section: SteelSection,
    fy: float,
    section_class: int,
    gamma_M0: float,
) -> Dict[str, Any]:
    props = section.properties

    if section_class <= 2:
        W = props.Wply
        basis = "plastic Wpl,y"
    elif section_class == 3:
        W = props.Wely
        basis = "elastic Wel,y"
    else:
        W = props.Wely
        basis = "elastic Wel,y used as conservative fallback; Class 4 effective section not implemented"

    M_c_Rd_kNm = W * fy / gamma_M0 / 1e6

    return {
        "basis": basis,
        "W_mm3": W,
        "M_c_Rd_kNm": M_c_Rd_kNm,
    }


def design_shear_resistance(
    section: SteelSection,
    fy: float,
    epsilon: float,
    gamma_M0: float,
) -> Dict[str, Any]:
    geo = section.geometry
    props = section.properties

    h_w = geo.h - 2.0 * geo.tf

    Av = max(
        props.A - 2.0 * geo.b * geo.tf + (geo.tw + 2.0 * geo.r) * geo.tf,
        h_w * geo.tw,
    )

    V_pl_Rd_kN = Av * (fy / math.sqrt(3.0)) / gamma_M0 / 1e3

    return {
        "Av_mm2": Av,
        "h_w_over_tw": h_w / geo.tw,
        "limit_72_epsilon": 72.0 * epsilon,
        "shear_buckling_check_required": (h_w / geo.tw) > 72.0 * epsilon,
        "V_pl_Rd_kN": V_pl_Rd_kN,
    }


def design_ltb_resistance(
    beam: Beam,
    M_c_Rd_kNm: float,
    L_cr_m: float,
    C1: float,
    kc: float,
    gamma_M1: float,
) -> Dict[str, Any]:
    sec = beam.section
    mat = beam.material
    geo = sec.geometry
    props = sec.properties

    E = mat.get_property("fe")
    G = mat.get_property("G")
    Iz = props.Iz
    It = props.It
    Iw = props.Iw
    L_cr_mm = L_cr_m * 1000.0

    term = (math.pi ** 2) * E * Iz / (L_cr_mm ** 2)
    warp = Iw / Iz
    tors = (L_cr_mm ** 2) * G * It / ((math.pi ** 2) * E * Iz)

    M_cr_kNm = C1 * term * math.sqrt(warp + tors) / 1e6

    if M_cr_kNm <= 0:
        raise ValueError("Mcr is invalid. Check Lcr and section torsional properties.")

    lambda_LT = math.sqrt(M_c_Rd_kNm / M_cr_kNm)

    if geo.h / geo.b <= 2.0:
        curve = "a"
        alpha_LT = 0.21
    else:
        curve = "b"
        alpha_LT = 0.34

    lambda_0 = 0.4
    beta = 0.75

    phi_LT = 0.5 * (
        1.0
        + alpha_LT * (lambda_LT - lambda_0)
        + beta * lambda_LT ** 2
    )

    radicand = max(phi_LT ** 2 - beta * lambda_LT ** 2, 0.0)
    chi_raw = 1.0 / (phi_LT + math.sqrt(radicand))
    chi_LT = min(chi_raw, 1.0, 1.0 / max(lambda_LT ** 2, 1e-9))

    f = min(
        1.0,
        1.0 - 0.5 * (1.0 - kc) * (1.0 - 2.0 * (lambda_LT - 0.8) ** 2),
    )

    chi_LT_mod = min(chi_LT / max(f, 1e-9), 1.0)
    M_b_Rd_kNm = chi_LT_mod * M_c_Rd_kNm / gamma_M1

    return {
        "M_cr_kNm": M_cr_kNm,
        "lambda_LT": lambda_LT,
        "curve": curve,
        "alpha_LT": alpha_LT,
        "phi_LT": phi_LT,
        "chi_LT": chi_LT,
        "kc": kc,
        "f": f,
        "chi_LT_mod": chi_LT_mod,
        "M_b_Rd_kNm": M_b_Rd_kNm,
    }


def design_web_bearing(
    beam: Beam,
    s_s_mm: float,
    gamma_M1: float,
) -> Dict[str, Any]:
    sec = beam.section
    mat = beam.material
    geo = sec.geometry

    fy = mat.get_property("fy")
    E = mat.get_property("fe")

    h_w = geo.h - 2.0 * geo.tf
    kF = 2.0 + 6.0 * s_s_mm / h_w
    F_cr_kN = 0.9 * kF * E * geo.tw ** 3 / h_w / 1e3

    m1 = geo.b / geo.tw
    m2 = 0.0

    ell_y = s_s_mm + 2.0 * geo.tf * (1.0 + math.sqrt(m1 + m2))
    lambda_F = math.sqrt(ell_y * geo.tw * fy / (F_cr_kN * 1e3))
    chi_F = min(0.5 / max(lambda_F, 1e-9), 1.0)

    if lambda_F > 0.5:
        m2 = 0.02 * (h_w / geo.tf) ** 2
        ell_y = s_s_mm + 2.0 * geo.tf * (1.0 + math.sqrt(m1 + m2))
        lambda_F = math.sqrt(ell_y * geo.tw * fy / (F_cr_kN * 1e3))
        chi_F = min(0.5 / max(lambda_F, 1e-9), 1.0)

    ell_eff = chi_F * ell_y
    F_Rd_kN = chi_F * fy * ell_eff * geo.tw / gamma_M1 / 1e3

    return {
        "kF": kF,
        "F_cr_kN": F_cr_kN,
        "m1": m1,
        "m2": m2,
        "ell_y_mm": ell_y,
        "lambda_F": lambda_F,
        "chi_F": chi_F,
        "ell_eff_mm": ell_eff,
        "F_Rd_kN": F_Rd_kN,
    }


def run_design_checks(
    beam: Beam,
    g_k_kn_m: float,
    q_k_kn_m: float,
    gamma_M0: float,
    gamma_M1: float,
    L_cr_m: float,
    C1: float,
    kc: float,
    s_s_mm: float,
) -> Dict[str, Any]:
    L = beam.length_m
    fy = beam.material.get_property("fy")

    w_Ed = 1.35 * g_k_kn_m + 1.50 * q_k_kn_m
    M_Ed = w_Ed * L ** 2 / 8.0
    V_Ed = w_Ed * L / 2.0

    cls = classify_section(beam.section, fy)
    bending = design_bending_resistance(
        beam.section,
        fy,
        cls["section_class"],
        gamma_M0,
    )
    shear = design_shear_resistance(
        beam.section,
        fy,
        cls["epsilon"],
        gamma_M0,
    )
    ltb = design_ltb_resistance(
        beam,
        bending["M_c_Rd_kNm"],
        L_cr_m,
        C1,
        kc,
        gamma_M1,
    )
    web_bearing = design_web_bearing(
        beam,
        s_s_mm,
        gamma_M1,
    )

    utilisations = {
        "bending": M_Ed / bending["M_c_Rd_kNm"],
        "shear": V_Ed / shear["V_pl_Rd_kN"],
        "ltb": M_Ed / ltb["M_b_Rd_kNm"],
        "web_bearing": V_Ed / web_bearing["F_Rd_kN"],
    }

    governing_check = max(utilisations, key=utilisations.get)
    overall_pass = utilisations[governing_check] <= 1.0

    return {
        "actions": {
            "g_k_kN_m": g_k_kn_m,
            "q_k_kN_m": q_k_kn_m,
            "w_Ed_kN_m": w_Ed,
            "M_Ed_kNm": M_Ed,
            "V_Ed_kN": V_Ed,
        },
        "classification": cls,
        "bending": bending,
        "shear": shear,
        "ltb": ltb,
        "web_bearing": web_bearing,
        "utilisations": utilisations,
        "governing_check": governing_check,
        "overall_pass": overall_pass,
    }


# ============================================================
# Steel section dynamic plot
# SVG I-section plot returned to frontend.
# ============================================================

def make_section_svg(section: SteelSection) -> str:
    geo = section.geometry

    view_w = 360.0
    view_h = 360.0
    margin = 40.0

    scale = min(
        (view_w - 2.0 * margin) / geo.b,
        (view_h - 2.0 * margin) / geo.h,
    )

    h = geo.h * scale
    b = geo.b * scale
    tw = max(geo.tw * scale, 2.0)
    tf = max(geo.tf * scale, 2.0)

    x0 = (view_w - b) / 2.0
    y0 = (view_h - h) / 2.0

    web_x = (view_w - tw) / 2.0
    top_y = y0
    bot_y = y0 + h - tf
    web_y = y0 + tf
    web_h = h - 2.0 * tf

    return f"""
<svg viewBox="0 0 {view_w:.0f} {view_h:.0f}" xmlns="http://www.w3.org/2000/svg" role="img">
  <rect x="0" y="0" width="{view_w:.0f}" height="{view_h:.0f}" fill="#f8fafc"/>
  <rect x="{x0:.2f}" y="{top_y:.2f}" width="{b:.2f}" height="{tf:.2f}" fill="#2563eb"/>
  <rect x="{web_x:.2f}" y="{web_y:.2f}" width="{tw:.2f}" height="{web_h:.2f}" fill="#2563eb"/>
  <rect x="{x0:.2f}" y="{bot_y:.2f}" width="{b:.2f}" height="{tf:.2f}" fill="#2563eb"/>
  <line x1="{x0:.2f}" y1="{y0 + h + 20:.2f}" x2="{x0 + b:.2f}" y2="{y0 + h + 20:.2f}" stroke="#334155" stroke-width="1.5"/>
  <line x1="{x0:.2f}" y1="{y0 + h + 15:.2f}" x2="{x0:.2f}" y2="{y0 + h + 25:.2f}" stroke="#334155" stroke-width="1.5"/>
  <line x1="{x0 + b:.2f}" y1="{y0 + h + 15:.2f}" x2="{x0 + b:.2f}" y2="{y0 + h + 25:.2f}" stroke="#334155" stroke-width="1.5"/>
  <text x="{view_w / 2:.2f}" y="{y0 + h + 38:.2f}" text-anchor="middle" font-size="13" fill="#334155">b = {geo.b:.1f} mm</text>
  <line x1="{x0 - 20:.2f}" y1="{y0:.2f}" x2="{x0 - 20:.2f}" y2="{y0 + h:.2f}" stroke="#334155" stroke-width="1.5"/>
  <line x1="{x0 - 25:.2f}" y1="{y0:.2f}" x2="{x0 - 15:.2f}" y2="{y0:.2f}" stroke="#334155" stroke-width="1.5"/>
  <line x1="{x0 - 25:.2f}" y1="{y0 + h:.2f}" x2="{x0 - 15:.2f}" y2="{y0 + h:.2f}" stroke="#334155" stroke-width="1.5"/>
  <text x="{x0 - 28:.2f}" y="{view_h / 2:.2f}" text-anchor="middle" font-size="13" fill="#334155" transform="rotate(-90 {x0 - 28:.2f} {view_h / 2:.2f})">h = {geo.h:.1f} mm</text>
  <text x="{view_w / 2:.2f}" y="24" text-anchor="middle" font-size="16" font-weight="700" fill="#0f172a">{section.name}</text>
</svg>
""".strip()


# ============================================================
# Helpers
# ============================================================

def parse_float(data: Dict[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_beam_from_payload(payload: Dict[str, Any]) -> Beam:
    section_name = payload.get("section", "IPE 300")
    material_name = payload.get("material", "S275")
    length_m = parse_float(payload, "length_m", 6.0)

    if section_name not in STEEL_SECTIONS:
        raise ValueError(f"Unknown steel section: {section_name}")

    if material_name not in STEEL_MATERIALS:
        raise ValueError(f"Unknown steel material: {material_name}")

    return Beam(
        id="beam-1",
        length_m=length_m,
        material=STEEL_MATERIALS[material_name],
        section=STEEL_SECTIONS[section_name],
    )


# ============================================================
# Routes
# ============================================================

@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        sections=list(STEEL_SECTIONS.keys()),
        materials=list(STEEL_MATERIALS.keys()),
    )


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        payload = request.get_json(force=True)
        beam = build_beam_from_payload(payload)

        support_left = payload.get("support_left", "fixed")
        support_right = payload.get("support_right", "roller")

        allowed_supports = {SupportType.FIXED.value, SupportType.ROLLER.value}
        if support_left not in allowed_supports or support_right not in allowed_supports:
            raise ValueError("Only fixed and roller supports are allowed.")

        # For this version, analysis remains simply supported single-span.
        # Support inputs are displayed/validated but not used for fixed-end frame analysis.
        w_service = parse_float(payload, "w_service_kN_m", 10.0)
        g_k = parse_float(payload, "g_k_kN_m", 5.0)
        q_k = parse_float(payload, "q_k_kN_m", 5.0)

        gamma_M0 = parse_float(payload, "gamma_M0", 1.0)
        gamma_M1 = parse_float(payload, "gamma_M1", 1.0)
        L_cr = parse_float(payload, "L_cr_m", beam.length_m)
        C1 = parse_float(payload, "C1", 1.0)
        kc = parse_float(payload, "kc", 1.0)
        s_s = parse_float(payload, "s_s_mm", 100.0)

        properties = get_beam_properties(beam)

        analysis = analyze_simply_supported_udl(
            beam=beam,
            w_kn_m=w_service,
            points=161,
        )

        design = run_design_checks(
            beam=beam,
            g_k_kn_m=g_k,
            q_k_kn_m=q_k,
            gamma_M0=gamma_M0,
            gamma_M1=gamma_M1,
            L_cr_m=L_cr,
            C1=C1,
            kc=kc,
            s_s_mm=s_s,
        )

        response = {
            "ok": True,
            "properties": properties,
            "analysis": analysis,
            "design": design,
            "section_svg": make_section_svg(beam.section),
            "summary": {
                "section": beam.section.name,
                "material": beam.material.name,
                "length_m": beam.length_m,
                "support_left": support_left,
                "support_right": support_right,
                "service_uniform_load_kN_m": w_service,
                "ULS_uniform_load_kN_m": design["actions"]["w_Ed_kN_m"],
                "max_service_moment_kNm": analysis["maxima"]["max_moment_kNm"],
                "max_service_shear_kN": analysis["maxima"]["max_shear_kN"],
                "max_service_deflection_mm": analysis["maxima"]["max_deflection_mm"],
                "M_Ed_kNm": design["actions"]["M_Ed_kNm"],
                "V_Ed_kN": design["actions"]["V_Ed_kN"],
                "governing_check": design["governing_check"],
                "governing_utilisation": design["utilisations"][design["governing_check"]],
                "overall_pass": design["overall_pass"],
            },
        }

        return jsonify(response)

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400


if __name__ == "__main__":
    app.run(debug=True)