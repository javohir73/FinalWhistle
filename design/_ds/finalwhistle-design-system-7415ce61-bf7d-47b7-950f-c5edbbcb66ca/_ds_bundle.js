/* @ds-bundle: {"format":3,"namespace":"FinalWhistleDesignSystem_7415ce","components":[{"name":"Flag","sourcePath":"components/brand/Flag.jsx"},{"name":"BrandMark","sourcePath":"components/brand/Logo.jsx"},{"name":"Wordmark","sourcePath":"components/brand/Logo.jsx"},{"name":"Logo","sourcePath":"components/brand/Logo.jsx"},{"name":"MatchCard","sourcePath":"components/brand/MatchCard.jsx"},{"name":"ProbabilityBar","sourcePath":"components/brand/ProbabilityBar.jsx"},{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Card","sourcePath":"components/core/Card.jsx"},{"name":"Input","sourcePath":"components/core/Input.jsx"}],"sourceHashes":{"components/brand/Flag.jsx":"825e6f296d2e","components/brand/Logo.jsx":"c38d21302c99","components/brand/MatchCard.jsx":"086a8278130e","components/brand/ProbabilityBar.jsx":"c02d9effbb05","components/core/Badge.jsx":"ea8d0eab4777","components/core/Button.jsx":"f6c1c2ec8314","components/core/Card.jsx":"f4dae3f3623a","components/core/Input.jsx":"bb877699ac9c"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.FinalWhistleDesignSystem_7415ce = window.FinalWhistleDesignSystem_7415ce || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/brand/Flag.jsx
try { (() => {
/** ISO country-code map for the World Cup nations (extend as needed). */
const CODES = {
  "Argentina": "ar",
  "Algeria": "dz",
  "Australia": "au",
  "Austria": "at",
  "Belgium": "be",
  "Brazil": "br",
  "Canada": "ca",
  "Cape Verde": "cv",
  "Colombia": "co",
  "Croatia": "hr",
  "Curaçao": "cw",
  "Czechia": "cz",
  "DR Congo": "cd",
  "England": "gb-eng",
  "France": "fr",
  "Germany": "de",
  "Ghana": "gh",
  "Italy": "it",
  "Japan": "jp",
  "Mexico": "mx",
  "Morocco": "ma",
  "Netherlands": "nl",
  "Portugal": "pt",
  "Senegal": "sn",
  "South Africa": "za",
  "South Korea": "kr",
  "Spain": "es",
  "USA": "us",
  "United States": "us",
  "Uruguay": "uy"
};
function initials(team) {
  return team.split(/\s+/).map(w => w[0]).join("").slice(0, 3).toUpperCase();
}

/**
 * Rounded flag chip. Loads from flagcdn by team name; falls back to a clean
 * typographic chip if the country is unknown or the image fails.
 */
function Flag({
  team,
  size = 28,
  code,
  className = "",
  style = {}
}) {
  const iso = code ?? CODES[team];
  const [failed, setFailed] = React.useState(false);
  if (!iso || failed) {
    return /*#__PURE__*/React.createElement("span", {
      className: className,
      "aria-hidden": true,
      style: {
        display: "grid",
        placeItems: "center",
        flexShrink: 0,
        width: size,
        height: size,
        borderRadius: "999px",
        background: "hsl(var(--c-surface-2))",
        color: "var(--text-muted)",
        fontSize: size * 0.36,
        fontWeight: 700,
        fontFamily: "var(--font-display)",
        boxShadow: "inset 0 0 0 1px var(--border-hairline)",
        ...style
      }
    }, initials(team));
  }
  return /*#__PURE__*/React.createElement("img", {
    src: `https://flagcdn.com/w80/${iso}.png`,
    alt: "",
    "aria-hidden": true,
    width: size,
    height: size,
    loading: "lazy",
    decoding: "async",
    referrerPolicy: "no-referrer",
    onError: () => setFailed(true),
    className: className,
    style: {
      width: size,
      height: size,
      flexShrink: 0,
      borderRadius: "999px",
      objectFit: "cover",
      boxShadow: "inset 0 0 0 1px hsl(var(--c-border) / 0.8)",
      ...style
    }
  });
}
Object.assign(__ds_scope, { Flag });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/Flag.jsx", error: String((e && e.message) || e) }); }

// components/brand/Logo.jsx
try { (() => {
/**
 * The FinalWhistle hexagon-whistle mark. Single-color: inherits currentColor,
 * so set the color with a `color` style or wrap. Pair with Wordmark.
 */
function BrandMark({
  size = 28,
  color = "hsl(var(--c-win))",
  className = "",
  style = {}
}) {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 172 156",
    fill: "none",
    className: className,
    "aria-hidden": "true",
    style: {
      height: size,
      width: "auto",
      color,
      ...style
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M46 0h80l46 78-46 78H46L0 78 46 0Z",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 9,
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("g", {
    transform: "translate(36 44)",
    fill: "currentColor"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z"
  })));
}

/**
 * The FinalWhistle wordmark — "Final" in foreground, "Whistle" in lime.
 * Always Bricolage display, tight tracking.
 */
function Wordmark({
  size = "1.125rem",
  weight = 800,
  className = "",
  style = {}
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: className,
    style: {
      fontFamily: "var(--font-display)",
      fontWeight: weight,
      fontSize: size,
      letterSpacing: "var(--tracking-tight)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-strong)"
    }
  }, "Final"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "hsl(var(--c-win))"
    }
  }, "Whistle"));
}

/** Lockup: mark + wordmark, the standard nav-left brand cluster. */
function Logo({
  size = 28,
  className = "",
  style = {}
}) {
  return /*#__PURE__*/React.createElement("span", {
    className: className,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.625rem",
      ...style
    }
  }, /*#__PURE__*/React.createElement(BrandMark, {
    size: size
  }), /*#__PURE__*/React.createElement(Wordmark, {
    size: `${size * 0.04}rem`
  }));
}
Object.assign(__ds_scope, { BrandMark, Wordmark, Logo });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/Logo.jsx", error: String((e && e.message) || e) }); }

// components/brand/ProbabilityBar.jsx
try { (() => {
function pct(v) {
  return `${Math.round(v * 100)}%`;
}

/**
 * The signature W/D/L stacked probability bar. Lime (home win) → amber (draw)
 * → rose (away win), proportional to the probabilities, with percentage labels.
 */
function ProbabilityBar({
  homeWin,
  draw,
  awayWin,
  homeLabel = "Home",
  awayLabel = "Away",
  showLabels = true,
  height = 10
}) {
  const seg = w => ({
    width: `${Math.max(0, w * 100)}%`
  });
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    role: "img",
    "aria-label": `${homeLabel} win ${pct(homeWin)}, draw ${pct(draw)}, ${awayLabel} win ${pct(awayWin)}`,
    style: {
      display: "flex",
      gap: 2,
      height,
      width: "100%",
      overflow: "hidden",
      borderRadius: "999px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      ...seg(homeWin),
      borderRadius: "999px 0 0 999px",
      background: "linear-gradient(90deg, hsl(var(--c-win) / 0.7), hsl(var(--c-win)))"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      ...seg(draw),
      background: "hsl(var(--c-draw) / 0.85)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      ...seg(awayWin),
      borderRadius: "0 999px 999px 0",
      background: "linear-gradient(90deg, hsl(var(--c-loss)), hsl(var(--c-loss) / 0.7))"
    }
  })), showLabels && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "0.5rem",
      display: "flex",
      justifyContent: "space-between",
      fontSize: "var(--text-2xs)",
      fontWeight: 500,
      fontVariantNumeric: "tabular-nums"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "hsl(var(--c-win))"
    }
  }, pct(homeWin)), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "hsl(var(--c-draw))"
    }
  }, pct(draw), " draw"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "hsl(var(--c-loss))"
    }
  }, pct(awayWin))));
}
Object.assign(__ds_scope, { ProbabilityBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/ProbabilityBar.jsx", error: String((e && e.message) || e) }); }

// components/core/Badge.jsx
try { (() => {
/**
 * Pill badge. Default neutral; semantic tones map to the W/D/L + gold palette.
 * `dot` adds a glowing status dot (the confidence-pill look).
 */
function Badge({
  children,
  tone = "neutral",
  dot = false,
  className = ""
}) {
  const tones = {
    neutral: {
      color: "var(--text-muted)",
      bg: "hsl(var(--c-surface-2) / 0.7)",
      ring: "var(--border-hairline)"
    },
    win: {
      color: "hsl(var(--c-win))",
      bg: "hsl(var(--c-win) / 0.1)",
      ring: "hsl(var(--c-win) / 0.3)"
    },
    draw: {
      color: "hsl(var(--c-draw))",
      bg: "hsl(var(--c-draw) / 0.1)",
      ring: "hsl(var(--c-draw) / 0.3)"
    },
    loss: {
      color: "hsl(var(--c-loss))",
      bg: "hsl(var(--c-loss) / 0.1)",
      ring: "hsl(var(--c-loss) / 0.3)"
    },
    gold: {
      color: "hsl(var(--c-gold))",
      bg: "hsl(var(--c-gold) / 0.12)",
      ring: "hsl(var(--c-gold) / 0.35)"
    }
  };
  const t = tones[tone] ?? tones.neutral;
  return /*#__PURE__*/React.createElement("span", {
    className: className,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.375rem",
      fontFamily: "var(--font-body)",
      fontSize: "var(--text-2xs)",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wide)",
      padding: dot ? "0.25rem 0.625rem" : "0.2rem 0.5rem",
      borderRadius: "var(--radius-pill)",
      color: t.color,
      background: t.bg,
      boxShadow: `inset 0 0 0 1px ${t.ring}`,
      whiteSpace: "nowrap"
    }
  }, dot && /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true,
    style: {
      width: "0.375rem",
      height: "0.375rem",
      borderRadius: "999px",
      background: "currentColor",
      boxShadow: "0 0 8px currentColor"
    }
  }), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/brand/MatchCard.jsx
try { (() => {
/**
 * The core dashboard match card: group eyebrow, status pill, both teams with
 * flags + scores, the W/D/L probability bar, and the predicted scoreline.
 * Composes Flag, ProbabilityBar and Badge.
 */
function MatchCard({
  group = "Group A",
  home,
  away,
  homeScore = null,
  awayScore = null,
  probabilities,
  predictedScore,
  status = "upcoming",
  // "upcoming" | "live" | "finished"
  liveLabel = "Live",
  confidence,
  // "High" | "Medium" | "Low"
  verdict,
  // { kind: "hit"|"miss", label } shown after a result
  onClick
}) {
  const finished = status === "finished";
  const live = status === "live";
  const showScore = (live || finished) && homeScore != null;
  const statusPill = live ? /*#__PURE__*/React.createElement(__ds_scope.Badge, {
    tone: "loss",
    dot: true
  }, liveLabel) : finished ? /*#__PURE__*/React.createElement(__ds_scope.Badge, {
    tone: "neutral"
  }, "Full time") : confidence ? /*#__PURE__*/React.createElement(__ds_scope.Badge, {
    tone: confidence === "High" ? "win" : confidence === "Medium" ? "draw" : "loss",
    dot: true
  }, confidence, " confidence") : null;
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClick,
    className: "fw-glass fw-card-hover",
    style: {
      borderRadius: "var(--radius-2xl)",
      padding: "1rem",
      cursor: onClick ? "pointer" : "default",
      boxShadow: live ? "inset 0 0 0 1px hsl(var(--c-loss) / 0.4)" : undefined
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: "0.75rem"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "fw-eyebrow"
  }, group), statusPill), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "0.625rem",
      marginBottom: "1rem"
    }
  }, /*#__PURE__*/React.createElement(TeamRow, {
    team: home,
    score: showScore ? homeScore : null
  }), /*#__PURE__*/React.createElement(TeamRow, {
    team: away,
    score: showScore ? awayScore : null
  })), probabilities && /*#__PURE__*/React.createElement(__ds_scope.ProbabilityBar, {
    homeWin: probabilities.homeWin,
    draw: probabilities.draw,
    awayWin: probabilities.awayWin,
    homeLabel: home,
    awayLabel: away
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "1rem",
      paddingTop: "0.75rem",
      borderTop: "1px solid hsl(var(--c-border) / 0.6)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: "0.5rem",
      fontSize: "var(--text-sm)"
    }
  }, verdict ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "0.3rem",
      fontSize: "var(--text-xs)",
      fontWeight: 600,
      color: verdict.kind === "miss" ? "hsl(var(--c-loss))" : "hsl(var(--c-win))"
    }
  }, /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true
  }, verdict.kind === "miss" ? "✗" : "✓"), verdict.label) : /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)"
    }
  }, "Winner ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text-strong)",
      fontWeight: 600
    }
  }, predictedScore?.winner ?? "—")), predictedScore && /*#__PURE__*/React.createElement("span", {
    className: "fw-chip",
    style: {
      borderRadius: "var(--radius-sm)",
      padding: "0.125rem 0.5rem",
      fontFamily: "var(--font-display)",
      fontSize: "var(--text-sm)",
      fontWeight: 700,
      fontVariantNumeric: "tabular-nums",
      color: "var(--text-strong)"
    }
  }, (live || finished) && /*#__PURE__*/React.createElement("span", {
    style: {
      marginRight: "0.375rem",
      fontSize: "var(--text-2xs)",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "var(--tracking-wide)",
      color: "var(--text-muted)"
    }
  }, "Predicted"), predictedScore.home, "\u2013", predictedScore.away)));
}
function TeamRow({
  team,
  score
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "0.625rem"
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.Flag, {
    team: team,
    size: 24
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      minWidth: 0,
      fontFamily: "var(--font-display)",
      fontSize: "0.9375rem",
      fontWeight: 600,
      letterSpacing: "var(--tracking-tight)",
      color: "var(--text-strong)"
    }
  }, team), score != null && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-display)",
      fontSize: "var(--text-lg)",
      fontWeight: 800,
      fontVariantNumeric: "tabular-nums",
      color: "var(--text-strong)"
    }
  }, score));
}
Object.assign(__ds_scope, { MatchCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/brand/MatchCard.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * FinalWhistle primary button. Lime-tinted "ghost-fill" by default (the app's
 * Sign-in / CTA style); `solid` for the bright lime call-to-action.
 */
function Button({
  children,
  variant = "primary",
  size = "md",
  iconLeft,
  iconRight,
  disabled = false,
  type = "button",
  onClick,
  className = "",
  ...rest
}) {
  const base = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "0.5rem",
    fontFamily: "var(--font-body)",
    fontWeight: 600,
    lineHeight: 1,
    borderRadius: "var(--radius-md)",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    transition: "background var(--dur-base) ease, border-color var(--dur-base) ease, transform var(--dur-fast) ease, color var(--dur-base) ease",
    border: "1px solid transparent",
    whiteSpace: "nowrap"
  };
  const sizes = {
    sm: {
      fontSize: "var(--text-sm)",
      padding: "0.4rem 0.75rem"
    },
    md: {
      fontSize: "var(--text-sm)",
      padding: "0.55rem 1rem"
    },
    lg: {
      fontSize: "var(--text-base)",
      padding: "0.75rem 1.4rem"
    }
  };
  const variants = {
    // Bright lime CTA — the "Use this" / "Save across devices" action.
    solid: {
      background: "hsl(var(--c-win))",
      color: "hsl(var(--c-background))",
      fontWeight: 700
    },
    // Lime ghost-fill — the default "Sign in" treatment.
    primary: {
      background: "hsl(var(--c-win) / 0.15)",
      color: "hsl(var(--c-win))",
      borderColor: "hsl(var(--c-win) / 0.3)"
    },
    // Neutral surface button.
    secondary: {
      background: "hsl(var(--c-surface-2) / 0.7)",
      color: "var(--text-strong)",
      borderColor: "var(--border-hairline)"
    },
    // Quiet, borderless.
    ghost: {
      background: "transparent",
      color: "var(--text-muted)"
    }
  };
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    onClick: onClick,
    className: className,
    style: {
      ...base,
      ...sizes[size],
      ...variants[variant]
    },
    onMouseEnter: e => {
      if (disabled) return;
      if (variant === "primary") e.currentTarget.style.background = "hsl(var(--c-win) / 0.25)";
      if (variant === "solid") e.currentTarget.style.filter = "brightness(1.06)";
      if (variant === "secondary") e.currentTarget.style.background = "hsl(var(--c-surface-2) / 0.95)";
      if (variant === "ghost") e.currentTarget.style.color = "var(--text-strong)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.filter = "";
      if (variant === "primary") e.currentTarget.style.background = "hsl(var(--c-win) / 0.15)";
      if (variant === "secondary") e.currentTarget.style.background = "hsl(var(--c-surface-2) / 0.7)";
      if (variant === "ghost") e.currentTarget.style.color = "var(--text-muted)";
    }
  }, rest), iconLeft, children, iconRight);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Glass surface card — the base container for almost everything in
 * FinalWhistle. Translucent gradient + blur + hairline border. Opt into the
 * 3px hover-lift with `hover`.
 */
function Card({
  children,
  hover = false,
  padding = "1rem",
  as = "div",
  className = "",
  style = {},
  ...rest
}) {
  const Tag = as;
  const [lift, setLift] = React.useState(false);
  return /*#__PURE__*/React.createElement(Tag, _extends({
    className: className,
    onMouseEnter: hover ? () => setLift(true) : undefined,
    onMouseLeave: hover ? () => setLift(false) : undefined,
    style: {
      background: "var(--glass-bg)",
      border: "var(--glass-border)",
      backdropFilter: "blur(var(--glass-blur))",
      WebkitBackdropFilter: "blur(var(--glass-blur))",
      borderRadius: "var(--radius-2xl)",
      padding,
      transition: "transform var(--dur-base) var(--ease-out-expo), border-color var(--dur-base) ease, box-shadow var(--dur-base) ease",
      transform: lift ? "translateY(-3px)" : "none",
      borderColor: lift ? "var(--border-accent)" : undefined,
      boxShadow: lift ? "var(--shadow-hover)" : undefined,
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Card.jsx", error: String((e && e.message) || e) }); }

// components/core/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Text input / search field, glass-surface styled with a lime focus ring. */
function Input({
  value,
  onChange,
  placeholder = "",
  iconLeft,
  type = "text",
  disabled = false,
  className = "",
  style = {},
  ...rest
}) {
  const [focus, setFocus] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    className: className,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "0.625rem",
      padding: "0.7rem 1rem",
      background: "hsl(var(--c-surface-2) / 0.6)",
      border: `1px solid ${focus ? "hsl(var(--c-win) / 0.5)" : "var(--border-hairline)"}`,
      borderRadius: "var(--radius-xl)",
      boxShadow: focus ? "0 0 0 3px hsl(var(--c-win) / 0.12)" : "none",
      transition: "border-color var(--dur-base) ease, box-shadow var(--dur-base) ease",
      opacity: disabled ? 0.5 : 1,
      ...style
    }
  }, iconLeft && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "flex",
      color: "var(--text-muted)",
      flexShrink: 0
    }
  }, iconLeft), /*#__PURE__*/React.createElement("input", _extends({
    type: type,
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    disabled: disabled,
    onFocus: () => setFocus(true),
    onBlur: () => setFocus(false),
    style: {
      flex: 1,
      minWidth: 0,
      border: "none",
      outline: "none",
      background: "transparent",
      color: "var(--text-strong)",
      fontFamily: "var(--font-body)",
      fontSize: "var(--text-base)"
    }
  }, rest)));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Input.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Flag = __ds_scope.Flag;

__ds_ns.BrandMark = __ds_scope.BrandMark;

__ds_ns.Wordmark = __ds_scope.Wordmark;

__ds_ns.Logo = __ds_scope.Logo;

__ds_ns.MatchCard = __ds_scope.MatchCard;

__ds_ns.ProbabilityBar = __ds_scope.ProbabilityBar;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Input = __ds_scope.Input;

})();
