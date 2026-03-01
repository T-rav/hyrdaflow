var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod2) => __copyProps(__defProp({}, "__esModule", { value: true }), mod2);

// node_modules/@csstools/css-color-parser/dist/index.mjs
var dist_exports = {};
__export(dist_exports, {
  ColorNotation: () => he,
  SyntaxFlag: () => me,
  color: () => color,
  colorDataFitsDisplayP3_Gamut: () => colorDataFitsDisplayP3_Gamut,
  colorDataFitsRGB_Gamut: () => colorDataFitsRGB_Gamut,
  serializeHSL: () => serializeHSL,
  serializeOKLCH: () => serializeOKLCH,
  serializeP3: () => serializeP3,
  serializeRGB: () => serializeRGB
});
module.exports = __toCommonJS(dist_exports);

// node_modules/@csstools/css-tokenizer/dist/index.mjs
var ParseError = class extends Error {
  sourceStart;
  sourceEnd;
  parserState;
  constructor(e3, n3, t3, o3) {
    super(e3), this.name = "ParseError", this.sourceStart = n3, this.sourceEnd = t3, this.parserState = o3;
  }
};
var ParseErrorWithToken = class extends ParseError {
  token;
  constructor(e3, n3, t3, o3, r3) {
    super(e3, n3, t3, o3), this.token = r3;
  }
};
var e = { UnexpectedNewLineInString: "Unexpected newline while consuming a string token.", UnexpectedEOFInString: "Unexpected EOF while consuming a string token.", UnexpectedEOFInComment: "Unexpected EOF while consuming a comment.", UnexpectedEOFInURL: "Unexpected EOF while consuming a url token.", UnexpectedEOFInEscapedCodePoint: "Unexpected EOF while consuming an escaped code point.", UnexpectedCharacterInURL: "Unexpected character while consuming a url token.", InvalidEscapeSequenceInURL: "Invalid escape sequence while consuming a url token.", InvalidEscapeSequenceAfterBackslash: 'Invalid escape sequence after "\\"' }, n = "undefined" != typeof globalThis && "structuredClone" in globalThis;
function cloneTokens(e3) {
  return n ? structuredClone(e3) : JSON.parse(JSON.stringify(e3));
}
function stringify(...e3) {
  let n3 = "";
  for (let t3 = 0; t3 < e3.length; t3++) n3 += e3[t3][1];
  return n3;
}
var t = 13, o = 45, r = 10, i = 43, s = 65533;
function checkIfFourCodePointsWouldStartCDO(e3) {
  return 60 === e3.source.codePointAt(e3.cursor) && 33 === e3.source.codePointAt(e3.cursor + 1) && e3.source.codePointAt(e3.cursor + 2) === o && e3.source.codePointAt(e3.cursor + 3) === o;
}
function isDigitCodePoint(e3) {
  return e3 >= 48 && e3 <= 57;
}
function isUppercaseLetterCodePoint(e3) {
  return e3 >= 65 && e3 <= 90;
}
function isLowercaseLetterCodePoint(e3) {
  return e3 >= 97 && e3 <= 122;
}
function isHexDigitCodePoint(e3) {
  return e3 >= 48 && e3 <= 57 || e3 >= 97 && e3 <= 102 || e3 >= 65 && e3 <= 70;
}
function isLetterCodePoint(e3) {
  return isLowercaseLetterCodePoint(e3) || isUppercaseLetterCodePoint(e3);
}
function isIdentStartCodePoint(e3) {
  return isLetterCodePoint(e3) || isNonASCII_IdentCodePoint(e3) || 95 === e3;
}
function isIdentCodePoint(e3) {
  return isIdentStartCodePoint(e3) || isDigitCodePoint(e3) || e3 === o;
}
function isNonASCII_IdentCodePoint(e3) {
  return 183 === e3 || 8204 === e3 || 8205 === e3 || 8255 === e3 || 8256 === e3 || 8204 === e3 || (192 <= e3 && e3 <= 214 || 216 <= e3 && e3 <= 246 || 248 <= e3 && e3 <= 893 || 895 <= e3 && e3 <= 8191 || 8304 <= e3 && e3 <= 8591 || 11264 <= e3 && e3 <= 12271 || 12289 <= e3 && e3 <= 55295 || 63744 <= e3 && e3 <= 64975 || 65008 <= e3 && e3 <= 65533 || (0 === e3 || (!!isSurrogate(e3) || e3 >= 65536)));
}
function isNonPrintableCodePoint(e3) {
  return 11 === e3 || 127 === e3 || 0 <= e3 && e3 <= 8 || 14 <= e3 && e3 <= 31;
}
function isNewLine(e3) {
  return e3 === r || e3 === t || 12 === e3;
}
function isWhitespace(e3) {
  return 32 === e3 || e3 === r || 9 === e3 || e3 === t || 12 === e3;
}
function isSurrogate(e3) {
  return e3 >= 55296 && e3 <= 57343;
}
function checkIfTwoCodePointsAreAValidEscape(e3) {
  return 92 === e3.source.codePointAt(e3.cursor) && !isNewLine(e3.source.codePointAt(e3.cursor + 1) ?? -1);
}
function checkIfThreeCodePointsWouldStartAnIdentSequence(e3, n3) {
  return n3.source.codePointAt(n3.cursor) === o ? n3.source.codePointAt(n3.cursor + 1) === o || (!!isIdentStartCodePoint(n3.source.codePointAt(n3.cursor + 1) ?? -1) || 92 === n3.source.codePointAt(n3.cursor + 1) && !isNewLine(n3.source.codePointAt(n3.cursor + 2) ?? -1)) : !!isIdentStartCodePoint(n3.source.codePointAt(n3.cursor) ?? -1) || checkIfTwoCodePointsAreAValidEscape(n3);
}
function checkIfThreeCodePointsWouldStartANumber(e3) {
  return e3.source.codePointAt(e3.cursor) === i || e3.source.codePointAt(e3.cursor) === o ? !!isDigitCodePoint(e3.source.codePointAt(e3.cursor + 1) ?? -1) || 46 === e3.source.codePointAt(e3.cursor + 1) && isDigitCodePoint(e3.source.codePointAt(e3.cursor + 2) ?? -1) : 46 === e3.source.codePointAt(e3.cursor) ? isDigitCodePoint(e3.source.codePointAt(e3.cursor + 1) ?? -1) : isDigitCodePoint(e3.source.codePointAt(e3.cursor) ?? -1);
}
function checkIfTwoCodePointsStartAComment(e3) {
  return 47 === e3.source.codePointAt(e3.cursor) && 42 === e3.source.codePointAt(e3.cursor + 1);
}
function checkIfThreeCodePointsWouldStartCDC(e3) {
  return e3.source.codePointAt(e3.cursor) === o && e3.source.codePointAt(e3.cursor + 1) === o && 62 === e3.source.codePointAt(e3.cursor + 2);
}
var c, a, u;
function mirrorVariantType(e3) {
  switch (e3) {
    case c.OpenParen:
      return c.CloseParen;
    case c.CloseParen:
      return c.OpenParen;
    case c.OpenCurly:
      return c.CloseCurly;
    case c.CloseCurly:
      return c.OpenCurly;
    case c.OpenSquare:
      return c.CloseSquare;
    case c.CloseSquare:
      return c.OpenSquare;
    default:
      return null;
  }
}
function mirrorVariant(e3) {
  switch (e3[0]) {
    case c.OpenParen:
      return [c.CloseParen, ")", -1, -1, void 0];
    case c.CloseParen:
      return [c.OpenParen, "(", -1, -1, void 0];
    case c.OpenCurly:
      return [c.CloseCurly, "}", -1, -1, void 0];
    case c.CloseCurly:
      return [c.OpenCurly, "{", -1, -1, void 0];
    case c.OpenSquare:
      return [c.CloseSquare, "]", -1, -1, void 0];
    case c.CloseSquare:
      return [c.OpenSquare, "[", -1, -1, void 0];
    default:
      return null;
  }
}
function consumeComment(n3, t3) {
  for (t3.advanceCodePoint(2); ; ) {
    const o3 = t3.readCodePoint();
    if (void 0 === o3) {
      const o4 = [c.Comment, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, void 0];
      return n3.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInComment, t3.representationStart, t3.representationEnd, ["4.3.2. Consume comments", "Unexpected EOF"], o4)), o4;
    }
    if (42 === o3 && (void 0 !== t3.source.codePointAt(t3.cursor) && 47 === t3.source.codePointAt(t3.cursor))) {
      t3.advanceCodePoint();
      break;
    }
  }
  return [c.Comment, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, void 0];
}
function consumeEscapedCodePoint(n3, o3) {
  const i3 = o3.readCodePoint();
  if (void 0 === i3) return n3.onParseError(new ParseError(e.UnexpectedEOFInEscapedCodePoint, o3.representationStart, o3.representationEnd, ["4.3.7. Consume an escaped code point", "Unexpected EOF"])), s;
  if (isHexDigitCodePoint(i3)) {
    const e3 = [i3];
    let n4;
    for (; void 0 !== (n4 = o3.source.codePointAt(o3.cursor)) && isHexDigitCodePoint(n4) && e3.length < 6; ) e3.push(n4), o3.advanceCodePoint();
    isWhitespace(o3.source.codePointAt(o3.cursor) ?? -1) && (o3.source.codePointAt(o3.cursor) === t && o3.source.codePointAt(o3.cursor + 1) === r && o3.advanceCodePoint(), o3.advanceCodePoint());
    const c3 = parseInt(String.fromCodePoint(...e3), 16);
    return 0 === c3 || isSurrogate(c3) || c3 > 1114111 ? s : c3;
  }
  return 0 === i3 || isSurrogate(i3) ? s : i3;
}
function consumeIdentSequence(e3, n3) {
  const t3 = [];
  for (; ; ) {
    const o3 = n3.source.codePointAt(n3.cursor) ?? -1;
    if (0 === o3 || isSurrogate(o3)) t3.push(s), n3.advanceCodePoint(+(o3 > 65535) + 1);
    else if (isIdentCodePoint(o3)) t3.push(o3), n3.advanceCodePoint(+(o3 > 65535) + 1);
    else {
      if (!checkIfTwoCodePointsAreAValidEscape(n3)) return t3;
      n3.advanceCodePoint(), t3.push(consumeEscapedCodePoint(e3, n3));
    }
  }
}
function consumeHashToken(e3, n3) {
  n3.advanceCodePoint();
  const t3 = n3.source.codePointAt(n3.cursor);
  if (void 0 !== t3 && (isIdentCodePoint(t3) || checkIfTwoCodePointsAreAValidEscape(n3))) {
    let t4 = u.Unrestricted;
    checkIfThreeCodePointsWouldStartAnIdentSequence(0, n3) && (t4 = u.ID);
    const o3 = consumeIdentSequence(e3, n3);
    return [c.Hash, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: String.fromCodePoint(...o3), type: t4 }];
  }
  return [c.Delim, "#", n3.representationStart, n3.representationEnd, { value: "#" }];
}
function consumeNumber(e3, n3) {
  let t3 = a.Integer;
  for (n3.source.codePointAt(n3.cursor) !== i && n3.source.codePointAt(n3.cursor) !== o || n3.advanceCodePoint(); isDigitCodePoint(n3.source.codePointAt(n3.cursor) ?? -1); ) n3.advanceCodePoint();
  if (46 === n3.source.codePointAt(n3.cursor) && isDigitCodePoint(n3.source.codePointAt(n3.cursor + 1) ?? -1)) for (n3.advanceCodePoint(2), t3 = a.Number; isDigitCodePoint(n3.source.codePointAt(n3.cursor) ?? -1); ) n3.advanceCodePoint();
  if (101 === n3.source.codePointAt(n3.cursor) || 69 === n3.source.codePointAt(n3.cursor)) {
    if (isDigitCodePoint(n3.source.codePointAt(n3.cursor + 1) ?? -1)) n3.advanceCodePoint(2);
    else {
      if (n3.source.codePointAt(n3.cursor + 1) !== o && n3.source.codePointAt(n3.cursor + 1) !== i || !isDigitCodePoint(n3.source.codePointAt(n3.cursor + 2) ?? -1)) return t3;
      n3.advanceCodePoint(3);
    }
    for (t3 = a.Number; isDigitCodePoint(n3.source.codePointAt(n3.cursor) ?? -1); ) n3.advanceCodePoint();
  }
  return t3;
}
function consumeNumericToken(e3, n3) {
  let t3;
  {
    const e4 = n3.source.codePointAt(n3.cursor);
    e4 === o ? t3 = "-" : e4 === i && (t3 = "+");
  }
  const r3 = consumeNumber(0, n3), s3 = parseFloat(n3.source.slice(n3.representationStart, n3.representationEnd + 1));
  if (checkIfThreeCodePointsWouldStartAnIdentSequence(0, n3)) {
    const o3 = consumeIdentSequence(e3, n3);
    return [c.Dimension, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: s3, signCharacter: t3, type: r3, unit: String.fromCodePoint(...o3) }];
  }
  return 37 === n3.source.codePointAt(n3.cursor) ? (n3.advanceCodePoint(), [c.Percentage, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: s3, signCharacter: t3 }]) : [c.Number, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: s3, signCharacter: t3, type: r3 }];
}
function consumeWhiteSpace(e3) {
  for (; isWhitespace(e3.source.codePointAt(e3.cursor) ?? -1); ) e3.advanceCodePoint();
  return [c.Whitespace, e3.source.slice(e3.representationStart, e3.representationEnd + 1), e3.representationStart, e3.representationEnd, void 0];
}
!function(e3) {
  e3.Comment = "comment", e3.AtKeyword = "at-keyword-token", e3.BadString = "bad-string-token", e3.BadURL = "bad-url-token", e3.CDC = "CDC-token", e3.CDO = "CDO-token", e3.Colon = "colon-token", e3.Comma = "comma-token", e3.Delim = "delim-token", e3.Dimension = "dimension-token", e3.EOF = "EOF-token", e3.Function = "function-token", e3.Hash = "hash-token", e3.Ident = "ident-token", e3.Number = "number-token", e3.Percentage = "percentage-token", e3.Semicolon = "semicolon-token", e3.String = "string-token", e3.URL = "url-token", e3.Whitespace = "whitespace-token", e3.OpenParen = "(-token", e3.CloseParen = ")-token", e3.OpenSquare = "[-token", e3.CloseSquare = "]-token", e3.OpenCurly = "{-token", e3.CloseCurly = "}-token", e3.UnicodeRange = "unicode-range-token";
}(c || (c = {})), function(e3) {
  e3.Integer = "integer", e3.Number = "number";
}(a || (a = {})), function(e3) {
  e3.Unrestricted = "unrestricted", e3.ID = "id";
}(u || (u = {}));
var Reader = class {
  cursor = 0;
  source = "";
  representationStart = 0;
  representationEnd = -1;
  constructor(e3) {
    this.source = e3;
  }
  advanceCodePoint(e3 = 1) {
    this.cursor = this.cursor + e3, this.representationEnd = this.cursor - 1;
  }
  readCodePoint() {
    const e3 = this.source.codePointAt(this.cursor);
    if (void 0 !== e3) return this.cursor = this.cursor + 1, this.representationEnd = this.cursor - 1, e3;
  }
  unreadCodePoint(e3 = 1) {
    this.cursor = this.cursor - e3, this.representationEnd = this.cursor - 1;
  }
  resetRepresentation() {
    this.representationStart = this.cursor, this.representationEnd = -1;
  }
};
function consumeStringToken(n3, o3) {
  let i3 = "";
  const a3 = o3.readCodePoint();
  for (; ; ) {
    const u3 = o3.readCodePoint();
    if (void 0 === u3) {
      const t3 = [c.String, o3.source.slice(o3.representationStart, o3.representationEnd + 1), o3.representationStart, o3.representationEnd, { value: i3 }];
      return n3.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInString, o3.representationStart, o3.representationEnd, ["4.3.5. Consume a string token", "Unexpected EOF"], t3)), t3;
    }
    if (isNewLine(u3)) {
      o3.unreadCodePoint();
      const i4 = [c.BadString, o3.source.slice(o3.representationStart, o3.representationEnd + 1), o3.representationStart, o3.representationEnd, void 0];
      return n3.onParseError(new ParseErrorWithToken(e.UnexpectedNewLineInString, o3.representationStart, o3.source.codePointAt(o3.cursor) === t && o3.source.codePointAt(o3.cursor + 1) === r ? o3.representationEnd + 2 : o3.representationEnd + 1, ["4.3.5. Consume a string token", "Unexpected newline"], i4)), i4;
    }
    if (u3 === a3) return [c.String, o3.source.slice(o3.representationStart, o3.representationEnd + 1), o3.representationStart, o3.representationEnd, { value: i3 }];
    if (92 !== u3) 0 === u3 || isSurrogate(u3) ? i3 += String.fromCodePoint(s) : i3 += String.fromCodePoint(u3);
    else {
      if (void 0 === o3.source.codePointAt(o3.cursor)) continue;
      if (isNewLine(o3.source.codePointAt(o3.cursor) ?? -1)) {
        o3.source.codePointAt(o3.cursor) === t && o3.source.codePointAt(o3.cursor + 1) === r && o3.advanceCodePoint(), o3.advanceCodePoint();
        continue;
      }
      i3 += String.fromCodePoint(consumeEscapedCodePoint(n3, o3));
    }
  }
}
function checkIfCodePointsMatchURLIdent(e3) {
  return !(3 !== e3.length || 117 !== e3[0] && 85 !== e3[0] || 114 !== e3[1] && 82 !== e3[1] || 108 !== e3[2] && 76 !== e3[2]);
}
function consumeBadURL(e3, n3) {
  for (; ; ) {
    const t3 = n3.source.codePointAt(n3.cursor);
    if (void 0 === t3) return;
    if (41 === t3) return void n3.advanceCodePoint();
    checkIfTwoCodePointsAreAValidEscape(n3) ? (n3.advanceCodePoint(), consumeEscapedCodePoint(e3, n3)) : n3.advanceCodePoint();
  }
}
function consumeUrlToken(n3, t3) {
  for (; isWhitespace(t3.source.codePointAt(t3.cursor) ?? -1); ) t3.advanceCodePoint();
  let o3 = "";
  for (; ; ) {
    if (void 0 === t3.source.codePointAt(t3.cursor)) {
      const r4 = [c.URL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, { value: o3 }];
      return n3.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInURL, t3.representationStart, t3.representationEnd, ["4.3.6. Consume a url token", "Unexpected EOF"], r4)), r4;
    }
    if (41 === t3.source.codePointAt(t3.cursor)) return t3.advanceCodePoint(), [c.URL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, { value: o3 }];
    if (isWhitespace(t3.source.codePointAt(t3.cursor) ?? -1)) {
      for (t3.advanceCodePoint(); isWhitespace(t3.source.codePointAt(t3.cursor) ?? -1); ) t3.advanceCodePoint();
      if (void 0 === t3.source.codePointAt(t3.cursor)) {
        const r4 = [c.URL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, { value: o3 }];
        return n3.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInURL, t3.representationStart, t3.representationEnd, ["4.3.6. Consume a url token", "Consume as much whitespace as possible", "Unexpected EOF"], r4)), r4;
      }
      return 41 === t3.source.codePointAt(t3.cursor) ? (t3.advanceCodePoint(), [c.URL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, { value: o3 }]) : (consumeBadURL(n3, t3), [c.BadURL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, void 0]);
    }
    const r3 = t3.source.codePointAt(t3.cursor);
    if (34 === r3 || 39 === r3 || 40 === r3 || isNonPrintableCodePoint(r3 ?? -1)) {
      consumeBadURL(n3, t3);
      const o4 = [c.BadURL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, void 0];
      return n3.onParseError(new ParseErrorWithToken(e.UnexpectedCharacterInURL, t3.representationStart, t3.representationEnd, ["4.3.6. Consume a url token", `Unexpected U+0022 QUOTATION MARK ("), U+0027 APOSTROPHE ('), U+0028 LEFT PARENTHESIS (() or non-printable code point`], o4)), o4;
    }
    if (92 === r3) {
      if (checkIfTwoCodePointsAreAValidEscape(t3)) {
        t3.advanceCodePoint(), o3 += String.fromCodePoint(consumeEscapedCodePoint(n3, t3));
        continue;
      }
      consumeBadURL(n3, t3);
      const r4 = [c.BadURL, t3.source.slice(t3.representationStart, t3.representationEnd + 1), t3.representationStart, t3.representationEnd, void 0];
      return n3.onParseError(new ParseErrorWithToken(e.InvalidEscapeSequenceInURL, t3.representationStart, t3.representationEnd, ["4.3.6. Consume a url token", "U+005C REVERSE SOLIDUS (\\)", "The input stream does not start with a valid escape sequence"], r4)), r4;
    }
    0 === t3.source.codePointAt(t3.cursor) || isSurrogate(t3.source.codePointAt(t3.cursor) ?? -1) ? (o3 += String.fromCodePoint(s), t3.advanceCodePoint()) : (o3 += t3.source[t3.cursor], t3.advanceCodePoint());
  }
}
function consumeIdentLikeToken(e3, n3) {
  const t3 = consumeIdentSequence(e3, n3);
  if (40 !== n3.source.codePointAt(n3.cursor)) return [c.Ident, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: String.fromCodePoint(...t3) }];
  if (checkIfCodePointsMatchURLIdent(t3)) {
    n3.advanceCodePoint();
    let o3 = 0;
    for (; ; ) {
      const e4 = isWhitespace(n3.source.codePointAt(n3.cursor) ?? -1), r3 = isWhitespace(n3.source.codePointAt(n3.cursor + 1) ?? -1);
      if (e4 && r3) {
        o3 += 1, n3.advanceCodePoint(1);
        continue;
      }
      const i3 = e4 ? n3.source.codePointAt(n3.cursor + 1) : n3.source.codePointAt(n3.cursor);
      if (34 === i3 || 39 === i3) return o3 > 0 && n3.unreadCodePoint(o3), [c.Function, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: String.fromCodePoint(...t3) }];
      break;
    }
    return consumeUrlToken(e3, n3);
  }
  return n3.advanceCodePoint(), [c.Function, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { value: String.fromCodePoint(...t3) }];
}
function checkIfThreeCodePointsWouldStartAUnicodeRange(e3) {
  return !(117 !== e3.source.codePointAt(e3.cursor) && 85 !== e3.source.codePointAt(e3.cursor) || e3.source.codePointAt(e3.cursor + 1) !== i || 63 !== e3.source.codePointAt(e3.cursor + 2) && !isHexDigitCodePoint(e3.source.codePointAt(e3.cursor + 2) ?? -1));
}
function consumeUnicodeRangeToken(e3, n3) {
  n3.advanceCodePoint(2);
  const t3 = [], r3 = [];
  let i3;
  for (; void 0 !== (i3 = n3.source.codePointAt(n3.cursor)) && t3.length < 6 && isHexDigitCodePoint(i3); ) t3.push(i3), n3.advanceCodePoint();
  for (; void 0 !== (i3 = n3.source.codePointAt(n3.cursor)) && t3.length < 6 && 63 === i3; ) 0 === r3.length && r3.push(...t3), t3.push(48), r3.push(70), n3.advanceCodePoint();
  if (!r3.length && n3.source.codePointAt(n3.cursor) === o && isHexDigitCodePoint(n3.source.codePointAt(n3.cursor + 1) ?? -1)) for (n3.advanceCodePoint(); void 0 !== (i3 = n3.source.codePointAt(n3.cursor)) && r3.length < 6 && isHexDigitCodePoint(i3); ) r3.push(i3), n3.advanceCodePoint();
  if (!r3.length) {
    const e4 = parseInt(String.fromCodePoint(...t3), 16);
    return [c.UnicodeRange, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { startOfRange: e4, endOfRange: e4 }];
  }
  const s3 = parseInt(String.fromCodePoint(...t3), 16), a3 = parseInt(String.fromCodePoint(...r3), 16);
  return [c.UnicodeRange, n3.source.slice(n3.representationStart, n3.representationEnd + 1), n3.representationStart, n3.representationEnd, { startOfRange: s3, endOfRange: a3 }];
}
function tokenize(e3, n3) {
  const t3 = tokenizer(e3, n3), o3 = [];
  for (; !t3.endOfFile(); ) o3.push(t3.nextToken());
  return o3.push(t3.nextToken()), o3;
}
function tokenizer(n3, s3) {
  const a3 = n3.css.valueOf(), u3 = n3.unicodeRangesAllowed ?? false, d3 = new Reader(a3), p2 = { onParseError: s3?.onParseError ?? noop };
  return { nextToken: function nextToken() {
    d3.resetRepresentation();
    const n4 = d3.source.codePointAt(d3.cursor);
    if (void 0 === n4) return [c.EOF, "", -1, -1, void 0];
    if (47 === n4 && checkIfTwoCodePointsStartAComment(d3)) return consumeComment(p2, d3);
    if (u3 && (117 === n4 || 85 === n4) && checkIfThreeCodePointsWouldStartAUnicodeRange(d3)) return consumeUnicodeRangeToken(0, d3);
    if (isIdentStartCodePoint(n4)) return consumeIdentLikeToken(p2, d3);
    if (isDigitCodePoint(n4)) return consumeNumericToken(p2, d3);
    switch (n4) {
      case 44:
        return d3.advanceCodePoint(), [c.Comma, ",", d3.representationStart, d3.representationEnd, void 0];
      case 58:
        return d3.advanceCodePoint(), [c.Colon, ":", d3.representationStart, d3.representationEnd, void 0];
      case 59:
        return d3.advanceCodePoint(), [c.Semicolon, ";", d3.representationStart, d3.representationEnd, void 0];
      case 40:
        return d3.advanceCodePoint(), [c.OpenParen, "(", d3.representationStart, d3.representationEnd, void 0];
      case 41:
        return d3.advanceCodePoint(), [c.CloseParen, ")", d3.representationStart, d3.representationEnd, void 0];
      case 91:
        return d3.advanceCodePoint(), [c.OpenSquare, "[", d3.representationStart, d3.representationEnd, void 0];
      case 93:
        return d3.advanceCodePoint(), [c.CloseSquare, "]", d3.representationStart, d3.representationEnd, void 0];
      case 123:
        return d3.advanceCodePoint(), [c.OpenCurly, "{", d3.representationStart, d3.representationEnd, void 0];
      case 125:
        return d3.advanceCodePoint(), [c.CloseCurly, "}", d3.representationStart, d3.representationEnd, void 0];
      case 39:
      case 34:
        return consumeStringToken(p2, d3);
      case 35:
        return consumeHashToken(p2, d3);
      case i:
      case 46:
        return checkIfThreeCodePointsWouldStartANumber(d3) ? consumeNumericToken(p2, d3) : (d3.advanceCodePoint(), [c.Delim, d3.source[d3.representationStart], d3.representationStart, d3.representationEnd, { value: d3.source[d3.representationStart] }]);
      case r:
      case t:
      case 12:
      case 9:
      case 32:
        return consumeWhiteSpace(d3);
      case o:
        return checkIfThreeCodePointsWouldStartANumber(d3) ? consumeNumericToken(p2, d3) : checkIfThreeCodePointsWouldStartCDC(d3) ? (d3.advanceCodePoint(3), [c.CDC, "-->", d3.representationStart, d3.representationEnd, void 0]) : checkIfThreeCodePointsWouldStartAnIdentSequence(0, d3) ? consumeIdentLikeToken(p2, d3) : (d3.advanceCodePoint(), [c.Delim, "-", d3.representationStart, d3.representationEnd, { value: "-" }]);
      case 60:
        return checkIfFourCodePointsWouldStartCDO(d3) ? (d3.advanceCodePoint(4), [c.CDO, "<!--", d3.representationStart, d3.representationEnd, void 0]) : (d3.advanceCodePoint(), [c.Delim, "<", d3.representationStart, d3.representationEnd, { value: "<" }]);
      case 64:
        if (d3.advanceCodePoint(), checkIfThreeCodePointsWouldStartAnIdentSequence(0, d3)) {
          const e3 = consumeIdentSequence(p2, d3);
          return [c.AtKeyword, d3.source.slice(d3.representationStart, d3.representationEnd + 1), d3.representationStart, d3.representationEnd, { value: String.fromCodePoint(...e3) }];
        }
        return [c.Delim, "@", d3.representationStart, d3.representationEnd, { value: "@" }];
      case 92: {
        if (checkIfTwoCodePointsAreAValidEscape(d3)) return consumeIdentLikeToken(p2, d3);
        d3.advanceCodePoint();
        const n5 = [c.Delim, "\\", d3.representationStart, d3.representationEnd, { value: "\\" }];
        return p2.onParseError(new ParseErrorWithToken(e.InvalidEscapeSequenceAfterBackslash, d3.representationStart, d3.representationEnd, ["4.3.1. Consume a token", "U+005C REVERSE SOLIDUS (\\)", "The input stream does not start with a valid escape sequence"], n5)), n5;
      }
    }
    return d3.advanceCodePoint(), [c.Delim, d3.source[d3.representationStart], d3.representationStart, d3.representationEnd, { value: d3.source[d3.representationStart] }];
  }, endOfFile: function endOfFile() {
    return void 0 === d3.source.codePointAt(d3.cursor);
  } };
}
function noop() {
}
function mutateIdent(e3, n3) {
  const t3 = [];
  for (const e4 of n3) t3.push(e4.codePointAt(0));
  const o3 = String.fromCodePoint(...serializeIdent(t3));
  e3[1] = o3, e3[4].value = n3;
}
function mutateUnit(e3, n3) {
  const t3 = [];
  for (const e4 of n3) t3.push(e4.codePointAt(0));
  const o3 = serializeIdent(t3);
  101 === o3[0] && insertEscapedCodePoint(o3, 0, o3[0]);
  const r3 = String.fromCodePoint(...o3), i3 = "+" === e3[4].signCharacter ? e3[4].signCharacter : "", s3 = e3[4].value.toString();
  e3[1] = `${i3}${s3}${r3}`, e3[4].unit = n3;
}
function serializeIdent(e3) {
  let n3 = 0;
  if (0 === e3[0]) e3.splice(0, 1, s), n3 = 1;
  else if (e3[0] === o && e3[1] === o) n3 = 2;
  else if (e3[0] === o && e3[1]) n3 = 2, isIdentStartCodePoint(e3[1]) || (n3 += insertEscapedCodePoint(e3, 1, e3[1]));
  else {
    if (e3[0] === o && !e3[1]) return [92, e3[0]];
    isIdentStartCodePoint(e3[0]) ? n3 = 1 : (n3 = 1, n3 += insertEscapedCodePoint(e3, 0, e3[0]));
  }
  for (let t3 = n3; t3 < e3.length; t3++) 0 !== e3[t3] ? isIdentCodePoint(e3[t3]) || (t3 += insertEscapedCharacter(e3, t3, e3[t3])) : (e3.splice(t3, 1, s), t3++);
  return e3;
}
function insertEscapedCharacter(e3, n3, t3) {
  return e3.splice(n3, 1, 92, t3), 1;
}
function insertEscapedCodePoint(e3, n3, t3) {
  const o3 = t3.toString(16), r3 = [];
  for (const e4 of o3) r3.push(e4.codePointAt(0));
  return e3.splice(n3, 1, 92, ...r3, 32), 1 + r3.length;
}
var d = Object.values(c);
function isToken(e3) {
  return !!Array.isArray(e3) && (!(e3.length < 4) && (!!d.includes(e3[0]) && ("string" == typeof e3[1] && ("number" == typeof e3[2] && "number" == typeof e3[3]))));
}
function isTokenNumeric(e3) {
  if (!e3) return false;
  switch (e3[0]) {
    case c.Dimension:
    case c.Number:
    case c.Percentage:
      return true;
    default:
      return false;
  }
}
function isTokenWhiteSpaceOrComment(e3) {
  if (!e3) return false;
  switch (e3[0]) {
    case c.Whitespace:
    case c.Comment:
      return true;
    default:
      return false;
  }
}
function isTokenAtKeyword(e3) {
  return !!e3 && e3[0] === c.AtKeyword;
}
function isTokenBadString(e3) {
  return !!e3 && e3[0] === c.BadString;
}
function isTokenBadURL(e3) {
  return !!e3 && e3[0] === c.BadURL;
}
function isTokenCDC(e3) {
  return !!e3 && e3[0] === c.CDC;
}
function isTokenCDO(e3) {
  return !!e3 && e3[0] === c.CDO;
}
function isTokenColon(e3) {
  return !!e3 && e3[0] === c.Colon;
}
function isTokenComma(e3) {
  return !!e3 && e3[0] === c.Comma;
}
function isTokenComment(e3) {
  return !!e3 && e3[0] === c.Comment;
}
function isTokenDelim(e3) {
  return !!e3 && e3[0] === c.Delim;
}
function isTokenDimension(e3) {
  return !!e3 && e3[0] === c.Dimension;
}
function isTokenEOF(e3) {
  return !!e3 && e3[0] === c.EOF;
}
function isTokenFunction(e3) {
  return !!e3 && e3[0] === c.Function;
}
function isTokenHash(e3) {
  return !!e3 && e3[0] === c.Hash;
}
function isTokenIdent(e3) {
  return !!e3 && e3[0] === c.Ident;
}
function isTokenNumber(e3) {
  return !!e3 && e3[0] === c.Number;
}
function isTokenPercentage(e3) {
  return !!e3 && e3[0] === c.Percentage;
}
function isTokenSemicolon(e3) {
  return !!e3 && e3[0] === c.Semicolon;
}
function isTokenString(e3) {
  return !!e3 && e3[0] === c.String;
}
function isTokenURL(e3) {
  return !!e3 && e3[0] === c.URL;
}
function isTokenWhitespace(e3) {
  return !!e3 && e3[0] === c.Whitespace;
}
function isTokenOpenParen(e3) {
  return !!e3 && e3[0] === c.OpenParen;
}
function isTokenCloseParen(e3) {
  return !!e3 && e3[0] === c.CloseParen;
}
function isTokenOpenSquare(e3) {
  return !!e3 && e3[0] === c.OpenSquare;
}
function isTokenCloseSquare(e3) {
  return !!e3 && e3[0] === c.CloseSquare;
}
function isTokenOpenCurly(e3) {
  return !!e3 && e3[0] === c.OpenCurly;
}
function isTokenCloseCurly(e3) {
  return !!e3 && e3[0] === c.CloseCurly;
}
function isTokenUnicodeRange(e3) {
  return !!e3 && e3[0] === c.UnicodeRange;
}

// node_modules/@csstools/color-helpers/dist/index.mjs
function multiplyMatrices(t3, n3) {
  return [t3[0] * n3[0] + t3[1] * n3[1] + t3[2] * n3[2], t3[3] * n3[0] + t3[4] * n3[1] + t3[5] * n3[2], t3[6] * n3[0] + t3[7] * n3[1] + t3[8] * n3[2]];
}
var t2 = [0.955473421488075, -0.02309845494876471, 0.06325924320057072, -0.0283697093338637, 1.0099953980813041, 0.021041441191917323, 0.012314014864481998, -0.020507649298898964, 1.330365926242124];
function D50_to_D65(n3) {
  return multiplyMatrices(t2, n3);
}
var n2 = [1.0479297925449969, 0.022946870601609652, -0.05019226628920524, 0.02962780877005599, 0.9904344267538799, -0.017073799063418826, -0.009243040646204504, 0.015055191490298152, 0.7518742814281371];
function D65_to_D50(t3) {
  return multiplyMatrices(n2, t3);
}
function HSL_to_sRGB(t3) {
  let n3 = t3[0] % 360;
  const _3 = t3[1] / 100, o3 = t3[2] / 100;
  return n3 < 0 && (n3 += 360), [HSL_to_sRGB_channel(0, n3, _3, o3), HSL_to_sRGB_channel(8, n3, _3, o3), HSL_to_sRGB_channel(4, n3, _3, o3)];
}
function HSL_to_sRGB_channel(t3, n3, _3, o3) {
  const e3 = (t3 + n3 / 30) % 12;
  return o3 - _3 * Math.min(o3, 1 - o3) * Math.max(-1, Math.min(e3 - 3, 9 - e3, 1));
}
function HWB_to_sRGB(t3) {
  const n3 = t3[0], _3 = t3[1] / 100, o3 = t3[2] / 100;
  if (_3 + o3 >= 1) {
    const t4 = _3 / (_3 + o3);
    return [t4, t4, t4];
  }
  const e3 = HSL_to_sRGB([n3, 100, 50]), a3 = 1 - _3 - o3;
  return [e3[0] * a3 + _3, e3[1] * a3 + _3, e3[2] * a3 + _3];
}
function LCH_to_Lab(t3) {
  const n3 = t3[2] * Math.PI / 180;
  return [t3[0], t3[1] * Math.cos(n3), t3[1] * Math.sin(n3)];
}
function Lab_to_LCH(t3) {
  const n3 = Math.sqrt(Math.pow(t3[1], 2) + Math.pow(t3[2], 2));
  let _3 = 180 * Math.atan2(t3[2], t3[1]) / Math.PI;
  return _3 < 0 && (_3 += 360), n3 <= 15e-4 && (_3 = NaN), [t3[0], n3, _3];
}
var _ = [0.3457 / 0.3585, 1, 0.2958 / 0.3585];
function Lab_to_XYZ(t3) {
  const n3 = 24389 / 27, o3 = 216 / 24389, e3 = (t3[0] + 16) / 116, a3 = t3[1] / 500 + e3, r3 = e3 - t3[2] / 200;
  return [(Math.pow(a3, 3) > o3 ? Math.pow(a3, 3) : (116 * a3 - 16) / n3) * _[0], (t3[0] > 8 ? Math.pow((t3[0] + 16) / 116, 3) : t3[0] / n3) * _[1], (Math.pow(r3, 3) > o3 ? Math.pow(r3, 3) : (116 * r3 - 16) / n3) * _[2]];
}
function OKLCH_to_OKLab(t3) {
  const n3 = t3[2] * Math.PI / 180;
  return [t3[0], t3[1] * Math.cos(n3), t3[1] * Math.sin(n3)];
}
function OKLab_to_OKLCH(t3) {
  const n3 = Math.sqrt(t3[1] ** 2 + t3[2] ** 2);
  let _3 = 180 * Math.atan2(t3[2], t3[1]) / Math.PI;
  return _3 < 0 && (_3 += 360), n3 <= 4e-6 && (_3 = NaN), [t3[0], n3, _3];
}
var o2 = [1.2268798758459243, -0.5578149944602171, 0.2813910456659647, -0.0405757452148008, 1.112286803280317, -0.0717110580655164, -0.0763729366746601, -0.4214933324022432, 1.5869240198367816], e2 = [1, 0.3963377773761749, 0.2158037573099136, 1, -0.1055613458156586, -0.0638541728258133, 1, -0.0894841775298119, -1.2914855480194092];
function OKLab_to_XYZ(t3) {
  const n3 = multiplyMatrices(e2, t3);
  return multiplyMatrices(o2, [n3[0] ** 3, n3[1] ** 3, n3[2] ** 3]);
}
function XYZ_to_Lab(t3) {
  const n3 = compute_f(t3[0] / _[0]), o3 = compute_f(t3[1] / _[1]);
  return [116 * o3 - 16, 500 * (n3 - o3), 200 * (o3 - compute_f(t3[2] / _[2]))];
}
var a2 = 216 / 24389, r2 = 24389 / 27;
function compute_f(t3) {
  return t3 > a2 ? Math.cbrt(t3) : (r2 * t3 + 16) / 116;
}
var l = [0.819022437996703, 0.3619062600528904, -0.1288737815209879, 0.0329836539323885, 0.9292868615863434, 0.0361446663506424, 0.0481771893596242, 0.2642395317527308, 0.6335478284694309], i2 = [0.210454268309314, 0.7936177747023054, -0.0040720430116193, 1.9779985324311684, -2.42859224204858, 0.450593709617411, 0.0259040424655478, 0.7827717124575296, -0.8086757549230774];
function XYZ_to_OKLab(t3) {
  const n3 = multiplyMatrices(l, t3);
  return multiplyMatrices(i2, [Math.cbrt(n3[0]), Math.cbrt(n3[1]), Math.cbrt(n3[2])]);
}
var c2 = [30757411 / 17917100, -6372589 / 17917100, -4539589 / 17917100, -0.666684351832489, 1.616481236634939, 467509 / 29648200, 792561 / 44930125, -1921689 / 44930125, 0.942103121235474];
var u2 = [446124 / 178915, -333277 / 357830, -72051 / 178915, -14852 / 17905, 63121 / 35810, 423 / 17905, 11844 / 330415, -50337 / 660830, 316169 / 330415];
function XYZ_to_lin_P3(t3) {
  return multiplyMatrices(u2, t3);
}
var s2 = [1.3457868816471583, -0.25557208737979464, -0.05110186497554526, -0.5446307051249019, 1.5082477428451468, 0.02052744743642139, 0, 0, 1.2119675456389452];
var h = [1829569 / 896150, -506331 / 896150, -308931 / 896150, -851781 / 878810, 1648619 / 878810, 36519 / 878810, 16779 / 1248040, -147721 / 1248040, 1266979 / 1248040];
var m = [12831 / 3959, -329 / 214, -1974 / 3959, -851781 / 878810, 1648619 / 878810, 36519 / 878810, 705 / 12673, -2585 / 12673, 705 / 667];
function XYZ_to_lin_sRGB(t3) {
  return multiplyMatrices(m, t3);
}
function gam_2020_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return n3 * Math.pow(_3, 1 / 2.4);
}
function gam_sRGB(t3) {
  return [gam_sRGB_channel(t3[0]), gam_sRGB_channel(t3[1]), gam_sRGB_channel(t3[2])];
}
function gam_sRGB_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return _3 > 31308e-7 ? n3 * (1.055 * Math.pow(_3, 1 / 2.4) - 0.055) : 12.92 * t3;
}
function gam_P3(t3) {
  return gam_sRGB(t3);
}
var D = 1 / 512;
function gam_ProPhoto_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return _3 >= D ? n3 * Math.pow(_3, 1 / 1.8) : 16 * t3;
}
function gam_a98rgb_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return n3 * Math.pow(_3, 256 / 563);
}
function lin_2020_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return n3 * Math.pow(_3, 2.4);
}
var b = [63426534 / 99577255, 20160776 / 139408157, 47086771 / 278816314, 26158966 / 99577255, 0.677998071518871, 8267143 / 139408157, 0, 19567812 / 697040785, 1.0609850577107909];
function lin_sRGB(t3) {
  return [lin_sRGB_channel(t3[0]), lin_sRGB_channel(t3[1]), lin_sRGB_channel(t3[2])];
}
function lin_sRGB_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return _3 <= 0.04045 ? t3 / 12.92 : n3 * Math.pow((_3 + 0.055) / 1.055, 2.4);
}
function lin_P3(t3) {
  return lin_sRGB(t3);
}
var g = [608311 / 1250200, 189793 / 714400, 198249 / 1000160, 35783 / 156275, 247089 / 357200, 198249 / 2500400, 0, 32229 / 714400, 5220557 / 5000800];
function lin_P3_to_XYZ(t3) {
  return multiplyMatrices(g, t3);
}
var X = 16 / 512;
function lin_ProPhoto_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return _3 <= X ? t3 / 16 : n3 * Math.pow(_3, 1.8);
}
var Y = [0.7977666449006423, 0.13518129740053308, 0.0313477341283922, 0.2880748288194013, 0.711835234241873, 8993693872564e-17, 0, 0, 0.8251046025104602];
function lin_a98rgb_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return n3 * Math.pow(_3, 563 / 256);
}
var Z = [573536 / 994567, 263643 / 1420810, 187206 / 994567, 591459 / 1989134, 6239551 / 9945670, 374412 / 4972835, 53769 / 1989134, 351524 / 4972835, 4929758 / 4972835];
var f = [506752 / 1228815, 87881 / 245763, 12673 / 70218, 87098 / 409605, 175762 / 245763, 12673 / 175545, 7918 / 409605, 87881 / 737289, 1001167 / 1053270];
function lin_sRGB_to_XYZ(t3) {
  return multiplyMatrices(f, t3);
}
function sRGB_to_HSL(t3) {
  const n3 = t3[0], _3 = t3[1], o3 = t3[2], e3 = Math.max(n3, _3, o3), a3 = Math.min(n3, _3, o3), r3 = (a3 + e3) / 2, l2 = e3 - a3;
  let i3 = Number.NaN, c3 = 0;
  if (0 !== Math.round(1e5 * l2)) {
    const t4 = Math.round(1e5 * r3);
    switch (c3 = 0 === t4 || 1e5 === t4 ? 0 : (e3 - r3) / Math.min(r3, 1 - r3), e3) {
      case n3:
        i3 = (_3 - o3) / l2 + (_3 < o3 ? 6 : 0);
        break;
      case _3:
        i3 = (o3 - n3) / l2 + 2;
        break;
      case o3:
        i3 = (n3 - _3) / l2 + 4;
    }
    i3 *= 60;
  }
  c3 < 0 && (i3 += 180, c3 = Math.abs(c3)), i3 >= 360 && (i3 -= 360);
  return c3 <= 1e-5 && (i3 = NaN), [i3, 100 * c3, 100 * r3];
}
function sRGB_to_Hue(t3) {
  const n3 = t3[0], _3 = t3[1], o3 = t3[2], e3 = Math.max(n3, _3, o3), a3 = Math.min(n3, _3, o3);
  let r3 = Number.NaN;
  const l2 = e3 - a3;
  if (0 !== l2) {
    switch (e3) {
      case n3:
        r3 = (_3 - o3) / l2 + (_3 < o3 ? 6 : 0);
        break;
      case _3:
        r3 = (o3 - n3) / l2 + 2;
        break;
      case o3:
        r3 = (n3 - _3) / l2 + 4;
    }
    r3 *= 60;
  }
  return r3 >= 360 && (r3 -= 360), r3;
}
function sRGB_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = lin_sRGB(n3), n3 = lin_sRGB_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_sRGB(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_lin_sRGB(n3), n3 = gam_sRGB(n3), n3;
}
function HSL_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = HSL_to_sRGB(n3), n3 = lin_sRGB(n3), n3 = lin_sRGB_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_HSL(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_lin_sRGB(n3), n3 = gam_sRGB(n3), n3 = sRGB_to_HSL(n3), n3;
}
function HWB_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = HWB_to_sRGB(n3), n3 = lin_sRGB(n3), n3 = lin_sRGB_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_HWB(t3) {
  let n3 = t3;
  n3 = D50_to_D65(n3), n3 = XYZ_to_lin_sRGB(n3);
  const _3 = gam_sRGB(n3), o3 = Math.min(_3[0], _3[1], _3[2]), e3 = 1 - Math.max(_3[0], _3[1], _3[2]);
  let a3 = sRGB_to_Hue(_3);
  return o3 + e3 >= 0.99999 && (a3 = NaN), [a3, 100 * o3, 100 * e3];
}
function Lab_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = Lab_to_XYZ(n3), n3;
}
function XYZ_D50_to_Lab(t3) {
  let n3 = t3;
  return n3 = XYZ_to_Lab(n3), n3;
}
function LCH_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = LCH_to_Lab(n3), n3 = Lab_to_XYZ(n3), n3;
}
function XYZ_D50_to_LCH(t3) {
  let n3 = t3;
  return n3 = XYZ_to_Lab(n3), n3 = Lab_to_LCH(n3), n3;
}
function OKLab_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = OKLab_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_OKLab(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_OKLab(n3), n3;
}
function OKLCH_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = OKLCH_to_OKLab(n3), n3 = OKLab_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_OKLCH(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_OKLab(n3), n3 = OKLab_to_OKLCH(n3), n3;
}
function lin_sRGB_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = lin_sRGB_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_lin_sRGB(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_lin_sRGB(n3), n3;
}
function a98_RGB_to_XYZ_D50(t3) {
  let n3 = t3;
  var _3;
  return n3 = [lin_a98rgb_channel((_3 = n3)[0]), lin_a98rgb_channel(_3[1]), lin_a98rgb_channel(_3[2])], n3 = multiplyMatrices(Z, n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_a98_RGB(t3) {
  let n3 = t3;
  var _3;
  return n3 = D50_to_D65(n3), n3 = multiplyMatrices(h, n3), n3 = [gam_a98rgb_channel((_3 = n3)[0]), gam_a98rgb_channel(_3[1]), gam_a98rgb_channel(_3[2])], n3;
}
function P3_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = lin_P3(n3), n3 = lin_P3_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_P3(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_lin_P3(n3), n3 = gam_P3(n3), n3;
}
function lin_P3_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = lin_P3_to_XYZ(n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_lin_P3(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3 = XYZ_to_lin_P3(n3), n3;
}
function rec_2020_to_XYZ_D50(t3) {
  let n3 = t3;
  var _3;
  return n3 = [lin_2020_channel((_3 = n3)[0]), lin_2020_channel(_3[1]), lin_2020_channel(_3[2])], n3 = multiplyMatrices(b, n3), n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_rec_2020(t3) {
  let n3 = t3;
  var _3;
  return n3 = D50_to_D65(n3), n3 = multiplyMatrices(c2, n3), n3 = [gam_2020_channel((_3 = n3)[0]), gam_2020_channel(_3[1]), gam_2020_channel(_3[2])], n3;
}
function ProPhoto_RGB_to_XYZ_D50(t3) {
  let n3 = t3;
  var _3;
  return n3 = [lin_ProPhoto_channel((_3 = n3)[0]), lin_ProPhoto_channel(_3[1]), lin_ProPhoto_channel(_3[2])], n3 = multiplyMatrices(Y, n3), n3;
}
function XYZ_D50_to_ProPhoto(t3) {
  let n3 = t3;
  var _3;
  return n3 = multiplyMatrices(s2, n3), n3 = [gam_ProPhoto_channel((_3 = n3)[0]), gam_ProPhoto_channel(_3[1]), gam_ProPhoto_channel(_3[2])], n3;
}
function XYZ_D65_to_XYZ_D50(t3) {
  let n3 = t3;
  return n3 = D65_to_D50(n3), n3;
}
function XYZ_D50_to_XYZ_D65(t3) {
  let n3 = t3;
  return n3 = D50_to_D65(n3), n3;
}
function XYZ_D50_to_XYZ_D50(t3) {
  return t3;
}
function inGamut(t3) {
  return t3[0] >= -1e-4 && t3[0] <= 1.0001 && t3[1] >= -1e-4 && t3[1] <= 1.0001 && t3[2] >= -1e-4 && t3[2] <= 1.0001;
}
function clip(t3) {
  return [t3[0] < 0 ? 0 : t3[0] > 1 ? 1 : t3[0], t3[1] < 0 ? 0 : t3[1] > 1 ? 1 : t3[1], t3[2] < 0 ? 0 : t3[2] > 1 ? 1 : t3[2]];
}
function deltaEOK(t3, n3) {
  const [_3, o3, e3] = t3, [a3, r3, l2] = n3, i3 = _3 - a3, c3 = o3 - r3, u3 = e3 - l2;
  return Math.sqrt(i3 ** 2 + c3 ** 2 + u3 ** 2);
}
var M = 0.02, p = 1e-4;
function mapGamut(t3, n3, _3) {
  const o3 = t3;
  let e3 = clip(n3(o3)), a3 = deltaEOK(OKLCH_to_OKLab(_3(e3)), OKLCH_to_OKLab(o3));
  if (a3 < M) return e3;
  let r3 = 0, l2 = o3[1], i3 = true;
  for (; l2 - r3 > p; ) {
    const t4 = (r3 + l2) / 2;
    if (o3[1] = t4, i3 && inGamut(n3(o3))) r3 = t4;
    else if (e3 = clip(n3(o3)), a3 = deltaEOK(OKLCH_to_OKLab(_3(e3)), OKLCH_to_OKLab(o3)), a3 < M) {
      if (M - a3 < p) return e3;
      i3 = false, r3 = t4;
    } else l2 = t4;
  }
  return clip(n3([...o3]));
}
function mapGamutRayTrace(t3, n3, _3) {
  const o3 = t3[0], e3 = t3[2];
  let a3 = n3(t3);
  const r3 = n3([o3, 0, e3]);
  for (let t4 = 0; t4 < 4; t4++) {
    if (t4 > 0) {
      const t5 = _3(a3);
      t5[0] = o3, t5[2] = e3, a3 = n3(t5);
    }
    const l2 = rayTraceBox(r3, a3);
    if (!l2) break;
    a3 = l2;
  }
  return clip(a3);
}
function rayTraceBox(t3, n3) {
  let _3 = 1 / 0, o3 = -1 / 0;
  const e3 = [0, 0, 0];
  for (let a3 = 0; a3 < 3; a3++) {
    const r3 = t3[a3], l2 = n3[a3] - r3;
    e3[a3] = l2;
    const i3 = 0, c3 = 1;
    if (l2) {
      const t4 = 1 / l2, n4 = (i3 - r3) * t4, e4 = (c3 - r3) * t4;
      o3 = Math.max(Math.min(n4, e4), o3), _3 = Math.min(Math.max(n4, e4), _3);
    } else if (r3 < i3 || r3 > c3) return false;
  }
  return !(o3 > _3 || _3 < 0) && (o3 < 0 && (o3 = _3), !!isFinite(o3) && [t3[0] + e3[0] * o3, t3[1] + e3[1] * o3, t3[2] + e3[2] * o3]);
}
var d2 = { aliceblue: [240, 248, 255], antiquewhite: [250, 235, 215], aqua: [0, 255, 255], aquamarine: [127, 255, 212], azure: [240, 255, 255], beige: [245, 245, 220], bisque: [255, 228, 196], black: [0, 0, 0], blanchedalmond: [255, 235, 205], blue: [0, 0, 255], blueviolet: [138, 43, 226], brown: [165, 42, 42], burlywood: [222, 184, 135], cadetblue: [95, 158, 160], chartreuse: [127, 255, 0], chocolate: [210, 105, 30], coral: [255, 127, 80], cornflowerblue: [100, 149, 237], cornsilk: [255, 248, 220], crimson: [220, 20, 60], cyan: [0, 255, 255], darkblue: [0, 0, 139], darkcyan: [0, 139, 139], darkgoldenrod: [184, 134, 11], darkgray: [169, 169, 169], darkgreen: [0, 100, 0], darkgrey: [169, 169, 169], darkkhaki: [189, 183, 107], darkmagenta: [139, 0, 139], darkolivegreen: [85, 107, 47], darkorange: [255, 140, 0], darkorchid: [153, 50, 204], darkred: [139, 0, 0], darksalmon: [233, 150, 122], darkseagreen: [143, 188, 143], darkslateblue: [72, 61, 139], darkslategray: [47, 79, 79], darkslategrey: [47, 79, 79], darkturquoise: [0, 206, 209], darkviolet: [148, 0, 211], deeppink: [255, 20, 147], deepskyblue: [0, 191, 255], dimgray: [105, 105, 105], dimgrey: [105, 105, 105], dodgerblue: [30, 144, 255], firebrick: [178, 34, 34], floralwhite: [255, 250, 240], forestgreen: [34, 139, 34], fuchsia: [255, 0, 255], gainsboro: [220, 220, 220], ghostwhite: [248, 248, 255], gold: [255, 215, 0], goldenrod: [218, 165, 32], gray: [128, 128, 128], green: [0, 128, 0], greenyellow: [173, 255, 47], grey: [128, 128, 128], honeydew: [240, 255, 240], hotpink: [255, 105, 180], indianred: [205, 92, 92], indigo: [75, 0, 130], ivory: [255, 255, 240], khaki: [240, 230, 140], lavender: [230, 230, 250], lavenderblush: [255, 240, 245], lawngreen: [124, 252, 0], lemonchiffon: [255, 250, 205], lightblue: [173, 216, 230], lightcoral: [240, 128, 128], lightcyan: [224, 255, 255], lightgoldenrodyellow: [250, 250, 210], lightgray: [211, 211, 211], lightgreen: [144, 238, 144], lightgrey: [211, 211, 211], lightpink: [255, 182, 193], lightsalmon: [255, 160, 122], lightseagreen: [32, 178, 170], lightskyblue: [135, 206, 250], lightslategray: [119, 136, 153], lightslategrey: [119, 136, 153], lightsteelblue: [176, 196, 222], lightyellow: [255, 255, 224], lime: [0, 255, 0], limegreen: [50, 205, 50], linen: [250, 240, 230], magenta: [255, 0, 255], maroon: [128, 0, 0], mediumaquamarine: [102, 205, 170], mediumblue: [0, 0, 205], mediumorchid: [186, 85, 211], mediumpurple: [147, 112, 219], mediumseagreen: [60, 179, 113], mediumslateblue: [123, 104, 238], mediumspringgreen: [0, 250, 154], mediumturquoise: [72, 209, 204], mediumvioletred: [199, 21, 133], midnightblue: [25, 25, 112], mintcream: [245, 255, 250], mistyrose: [255, 228, 225], moccasin: [255, 228, 181], navajowhite: [255, 222, 173], navy: [0, 0, 128], oldlace: [253, 245, 230], olive: [128, 128, 0], olivedrab: [107, 142, 35], orange: [255, 165, 0], orangered: [255, 69, 0], orchid: [218, 112, 214], palegoldenrod: [238, 232, 170], palegreen: [152, 251, 152], paleturquoise: [175, 238, 238], palevioletred: [219, 112, 147], papayawhip: [255, 239, 213], peachpuff: [255, 218, 185], peru: [205, 133, 63], pink: [255, 192, 203], plum: [221, 160, 221], powderblue: [176, 224, 230], purple: [128, 0, 128], rebeccapurple: [102, 51, 153], red: [255, 0, 0], rosybrown: [188, 143, 143], royalblue: [65, 105, 225], saddlebrown: [139, 69, 19], salmon: [250, 128, 114], sandybrown: [244, 164, 96], seagreen: [46, 139, 87], seashell: [255, 245, 238], sienna: [160, 82, 45], silver: [192, 192, 192], skyblue: [135, 206, 235], slateblue: [106, 90, 205], slategray: [112, 128, 144], slategrey: [112, 128, 144], snow: [255, 250, 250], springgreen: [0, 255, 127], steelblue: [70, 130, 180], tan: [210, 180, 140], teal: [0, 128, 128], thistle: [216, 191, 216], tomato: [255, 99, 71], turquoise: [64, 224, 208], violet: [238, 130, 238], wheat: [245, 222, 179], white: [255, 255, 255], whitesmoke: [245, 245, 245], yellow: [255, 255, 0], yellowgreen: [154, 205, 50] };
function luminance(t3) {
  const [n3, _3, o3] = t3.map((t4) => t4 <= 0.04045 ? t4 / 12.92 : Math.pow((t4 + 0.055) / 1.055, 2.4));
  return 0.2126 * n3 + 0.7152 * _3 + 0.0722 * o3;
}
function contrast_ratio_wcag_2_1(t3, n3) {
  const _3 = luminance(t3), o3 = luminance(n3);
  return (Math.max(_3, o3) + 0.05) / (Math.min(_3, o3) + 0.05);
}

// node_modules/@csstools/css-parser-algorithms/dist/index.mjs
var f2;
function walkerIndexGenerator(e3) {
  let n3 = e3.slice();
  return (e4, t3, o3) => {
    let s3 = -1;
    for (let i3 = n3.indexOf(t3); i3 < n3.length && (s3 = e4.indexOf(n3[i3]), -1 === s3 || s3 < o3); i3++) ;
    return -1 === s3 || s3 === o3 && t3 === e4[o3] && (s3++, s3 >= e4.length) ? -1 : (n3 = e4.slice(), s3);
  };
}
function consumeComponentValue(e3, n3) {
  const t3 = n3[0];
  if (isTokenOpenParen(t3) || isTokenOpenCurly(t3) || isTokenOpenSquare(t3)) {
    const t4 = consumeSimpleBlock(e3, n3);
    return { advance: t4.advance, node: t4.node };
  }
  if (isTokenFunction(t3)) {
    const t4 = consumeFunction(e3, n3);
    return { advance: t4.advance, node: t4.node };
  }
  if (isTokenWhitespace(t3)) {
    const t4 = consumeWhitespace(e3, n3);
    return { advance: t4.advance, node: t4.node };
  }
  if (isTokenComment(t3)) {
    const t4 = consumeComment2(e3, n3);
    return { advance: t4.advance, node: t4.node };
  }
  return { advance: 1, node: new TokenNode(t3) };
}
!function(e3) {
  e3.Function = "function", e3.SimpleBlock = "simple-block", e3.Whitespace = "whitespace", e3.Comment = "comment", e3.Token = "token";
}(f2 || (f2 = {}));
var ContainerNodeBaseClass = class {
  value = [];
  indexOf(e3) {
    return this.value.indexOf(e3);
  }
  at(e3) {
    if ("number" == typeof e3) return e3 < 0 && (e3 = this.value.length + e3), this.value[e3];
  }
  forEach(e3, n3) {
    if (0 === this.value.length) return;
    const t3 = walkerIndexGenerator(this.value);
    let o3 = 0;
    for (; o3 < this.value.length; ) {
      const s3 = this.value[o3];
      let i3;
      if (n3 && (i3 = { ...n3 }), false === e3({ node: s3, parent: this, state: i3 }, o3)) return false;
      if (o3 = t3(this.value, s3, o3), -1 === o3) break;
    }
  }
  walk(e3, n3) {
    0 !== this.value.length && this.forEach((n4, t3) => false !== e3(n4, t3) && ((!("walk" in n4.node) || !this.value.includes(n4.node) || false !== n4.node.walk(e3, n4.state)) && void 0), n3);
  }
};
var FunctionNode = class _FunctionNode extends ContainerNodeBaseClass {
  type = f2.Function;
  name;
  endToken;
  constructor(e3, n3, t3) {
    super(), this.name = e3, this.endToken = n3, this.value = t3;
  }
  getName() {
    return this.name[4].value;
  }
  normalize() {
    isTokenEOF(this.endToken) && (this.endToken = [c.CloseParen, ")", -1, -1, void 0]);
  }
  tokens() {
    return isTokenEOF(this.endToken) ? [this.name, ...this.value.flatMap((e3) => e3.tokens())] : [this.name, ...this.value.flatMap((e3) => e3.tokens()), this.endToken];
  }
  toString() {
    const e3 = this.value.map((e4) => isToken(e4) ? stringify(e4) : e4.toString()).join("");
    return stringify(this.name) + e3 + stringify(this.endToken);
  }
  toJSON() {
    return { type: this.type, name: this.getName(), tokens: this.tokens(), value: this.value.map((e3) => e3.toJSON()) };
  }
  isFunctionNode() {
    return _FunctionNode.isFunctionNode(this);
  }
  static isFunctionNode(e3) {
    return !!e3 && (e3 instanceof _FunctionNode && e3.type === f2.Function);
  }
};
function consumeFunction(n3, t3) {
  const o3 = [];
  let s3 = 1;
  for (; ; ) {
    const i3 = t3[s3];
    if (!i3 || isTokenEOF(i3)) return n3.onParseError(new ParseError("Unexpected EOF while consuming a function.", t3[0][2], t3[t3.length - 1][3], ["5.4.9. Consume a function", "Unexpected EOF"])), { advance: t3.length, node: new FunctionNode(t3[0], i3, o3) };
    if (isTokenCloseParen(i3)) return { advance: s3 + 1, node: new FunctionNode(t3[0], i3, o3) };
    if (isTokenWhiteSpaceOrComment(i3)) {
      const e3 = consumeAllCommentsAndWhitespace(n3, t3.slice(s3));
      s3 += e3.advance, o3.push(...e3.nodes);
      continue;
    }
    const r3 = consumeComponentValue(n3, t3.slice(s3));
    s3 += r3.advance, o3.push(r3.node);
  }
}
var SimpleBlockNode = class _SimpleBlockNode extends ContainerNodeBaseClass {
  type = f2.SimpleBlock;
  startToken;
  endToken;
  constructor(e3, n3, t3) {
    super(), this.startToken = e3, this.endToken = n3, this.value = t3;
  }
  normalize() {
    if (isTokenEOF(this.endToken)) {
      const e3 = mirrorVariant(this.startToken);
      e3 && (this.endToken = e3);
    }
  }
  tokens() {
    return isTokenEOF(this.endToken) ? [this.startToken, ...this.value.flatMap((e3) => e3.tokens())] : [this.startToken, ...this.value.flatMap((e3) => e3.tokens()), this.endToken];
  }
  toString() {
    const e3 = this.value.map((e4) => isToken(e4) ? stringify(e4) : e4.toString()).join("");
    return stringify(this.startToken) + e3 + stringify(this.endToken);
  }
  toJSON() {
    return { type: this.type, startToken: this.startToken, tokens: this.tokens(), value: this.value.map((e3) => e3.toJSON()) };
  }
  isSimpleBlockNode() {
    return _SimpleBlockNode.isSimpleBlockNode(this);
  }
  static isSimpleBlockNode(e3) {
    return !!e3 && (e3 instanceof _SimpleBlockNode && e3.type === f2.SimpleBlock);
  }
};
function consumeSimpleBlock(n3, t3) {
  const o3 = mirrorVariantType(t3[0][0]);
  if (!o3) throw new Error("Failed to parse, a mirror variant must exist for all block open tokens.");
  const s3 = [];
  let i3 = 1;
  for (; ; ) {
    const r3 = t3[i3];
    if (!r3 || isTokenEOF(r3)) return n3.onParseError(new ParseError("Unexpected EOF while consuming a simple block.", t3[0][2], t3[t3.length - 1][3], ["5.4.8. Consume a simple block", "Unexpected EOF"])), { advance: t3.length, node: new SimpleBlockNode(t3[0], r3, s3) };
    if (r3[0] === o3) return { advance: i3 + 1, node: new SimpleBlockNode(t3[0], r3, s3) };
    if (isTokenWhiteSpaceOrComment(r3)) {
      const e3 = consumeAllCommentsAndWhitespace(n3, t3.slice(i3));
      i3 += e3.advance, s3.push(...e3.nodes);
      continue;
    }
    const a3 = consumeComponentValue(n3, t3.slice(i3));
    i3 += a3.advance, s3.push(a3.node);
  }
}
var WhitespaceNode = class _WhitespaceNode {
  type = f2.Whitespace;
  value;
  constructor(e3) {
    this.value = e3;
  }
  tokens() {
    return this.value;
  }
  toString() {
    return stringify(...this.value);
  }
  toJSON() {
    return { type: this.type, tokens: this.tokens() };
  }
  isWhitespaceNode() {
    return _WhitespaceNode.isWhitespaceNode(this);
  }
  static isWhitespaceNode(e3) {
    return !!e3 && (e3 instanceof _WhitespaceNode && e3.type === f2.Whitespace);
  }
};
function consumeWhitespace(e3, n3) {
  let t3 = 0;
  for (; ; ) {
    const e4 = n3[t3];
    if (!isTokenWhitespace(e4)) return { advance: t3, node: new WhitespaceNode(n3.slice(0, t3)) };
    t3++;
  }
}
var CommentNode = class _CommentNode {
  type = f2.Comment;
  value;
  constructor(e3) {
    this.value = e3;
  }
  tokens() {
    return [this.value];
  }
  toString() {
    return stringify(this.value);
  }
  toJSON() {
    return { type: this.type, tokens: this.tokens() };
  }
  isCommentNode() {
    return _CommentNode.isCommentNode(this);
  }
  static isCommentNode(e3) {
    return !!e3 && (e3 instanceof _CommentNode && e3.type === f2.Comment);
  }
};
function consumeComment2(e3, n3) {
  return { advance: 1, node: new CommentNode(n3[0]) };
}
function consumeAllCommentsAndWhitespace(e3, n3) {
  const t3 = [];
  let o3 = 0;
  for (; ; ) {
    if (isTokenWhitespace(n3[o3])) {
      const e4 = consumeWhitespace(0, n3.slice(o3));
      o3 += e4.advance, t3.push(e4.node);
      continue;
    }
    if (!isTokenComment(n3[o3])) return { advance: o3, nodes: t3 };
    t3.push(new CommentNode(n3[o3])), o3++;
  }
}
var TokenNode = class _TokenNode {
  type = f2.Token;
  value;
  constructor(e3) {
    this.value = e3;
  }
  tokens() {
    return [this.value];
  }
  toString() {
    return this.value[1];
  }
  toJSON() {
    return { type: this.type, tokens: this.tokens() };
  }
  isTokenNode() {
    return _TokenNode.isTokenNode(this);
  }
  static isTokenNode(e3) {
    return !!e3 && (e3 instanceof _TokenNode && e3.type === f2.Token);
  }
};
function parseComponentValue(t3, o3) {
  const s3 = { onParseError: o3?.onParseError ?? (() => {
  }) }, i3 = [...t3];
  isTokenEOF(i3[i3.length - 1]) || i3.push([c.EOF, "", i3[i3.length - 1][2], i3[i3.length - 1][3], void 0]);
  const r3 = consumeComponentValue(s3, i3);
  if (isTokenEOF(i3[Math.min(r3.advance, i3.length - 1)])) return r3.node;
  s3.onParseError(new ParseError("Expected EOF after parsing a component value.", t3[0][2], t3[t3.length - 1][3], ["5.3.9. Parse a component value", "Expected EOF"]));
}
function parseListOfComponentValues(t3, o3) {
  const s3 = { onParseError: o3?.onParseError ?? (() => {
  }) }, i3 = [...t3];
  isTokenEOF(i3[i3.length - 1]) && i3.push([c.EOF, "", i3[i3.length - 1][2], i3[i3.length - 1][3], void 0]);
  const r3 = [];
  let a3 = 0;
  for (; ; ) {
    if (!i3[a3] || isTokenEOF(i3[a3])) return r3;
    const n3 = consumeComponentValue(s3, i3.slice(a3));
    r3.push(n3.node), a3 += n3.advance;
  }
}
function parseCommaSeparatedListOfComponentValues(t3, o3) {
  const s3 = { onParseError: o3?.onParseError ?? (() => {
  }) }, i3 = [...t3];
  if (0 === t3.length) return [];
  isTokenEOF(i3[i3.length - 1]) && i3.push([c.EOF, "", i3[i3.length - 1][2], i3[i3.length - 1][3], void 0]);
  const r3 = [];
  let a3 = [], c3 = 0;
  for (; ; ) {
    if (!i3[c3] || isTokenEOF(i3[c3])) return a3.length && r3.push(a3), r3;
    if (isTokenComma(i3[c3])) {
      r3.push(a3), a3 = [], c3++;
      continue;
    }
    const n3 = consumeComponentValue(s3, t3.slice(c3));
    a3.push(n3.node), c3 += n3.advance;
  }
}
function gatherNodeAncestry(e3) {
  const n3 = /* @__PURE__ */ new Map();
  return e3.walk((e4) => {
    Array.isArray(e4.node) ? e4.node.forEach((t3) => {
      n3.set(t3, e4.parent);
    }) : n3.set(e4.node, e4.parent);
  }), n3;
}
function forEach(e3, n3, t3) {
  if (0 === e3.length) return;
  const o3 = walkerIndexGenerator(e3);
  let s3 = 0;
  for (; s3 < e3.length; ) {
    const i3 = e3[s3];
    let r3;
    if (t3 && (r3 = { ...t3 }), false === n3({ node: i3, parent: { value: e3 }, state: r3 }, s3)) return false;
    if (s3 = o3(e3, i3, s3), -1 === s3) break;
  }
}
function walk(e3, n3, t3) {
  0 !== e3.length && forEach(e3, (t4, o3) => false !== n3(t4, o3) && ((!("walk" in t4.node) || !e3.includes(t4.node) || false !== t4.node.walk(n3, t4.state)) && void 0), t3);
}
function replaceComponentValues(e3, n3) {
  for (let t3 = 0; t3 < e3.length; t3++) {
    walk(e3[t3], (e4, t4) => {
      if ("number" != typeof t4) return;
      const o3 = n3(e4.node);
      o3 && (Array.isArray(o3) ? e4.parent.value.splice(t4, 1, ...o3) : e4.parent.value.splice(t4, 1, o3));
    });
  }
  return e3;
}
function stringify2(e3) {
  return e3.map((e4) => e4.map((e5) => stringify(...e5.tokens())).join("")).join(",");
}
function isSimpleBlockNode(e3) {
  return SimpleBlockNode.isSimpleBlockNode(e3);
}
function isFunctionNode(e3) {
  return FunctionNode.isFunctionNode(e3);
}
function isWhitespaceNode(e3) {
  return WhitespaceNode.isWhitespaceNode(e3);
}
function isCommentNode(e3) {
  return CommentNode.isCommentNode(e3);
}
function isWhiteSpaceOrCommentNode(e3) {
  return isWhitespaceNode(e3) || isCommentNode(e3);
}
function isTokenNode(e3) {
  return TokenNode.isTokenNode(e3);
}
function sourceIndices(e3) {
  if (Array.isArray(e3)) {
    const n4 = e3[0];
    if (!n4) return [0, 0];
    const t4 = e3[e3.length - 1] || n4;
    return [sourceIndices(n4)[0], sourceIndices(t4)[1]];
  }
  const n3 = e3.tokens(), t3 = n3[0], o3 = n3[n3.length - 1];
  return t3 && o3 ? [t3[2], o3[3]] : [0, 0];
}

// node_modules/@csstools/css-calc/dist/index.mjs
var ParseError2 = class extends Error {
  sourceStart;
  sourceEnd;
  constructor(e3, n3, t3) {
    super(e3), this.name = "ParseError", this.sourceStart = n3, this.sourceEnd = t3;
  }
};
var ParseErrorWithComponentValues = class extends ParseError2 {
  componentValues;
  constructor(n3, t3) {
    super(n3, ...sourceIndices(t3)), this.componentValues = t3;
  }
};
var y = { UnexpectedAdditionOfDimensionOrPercentageWithNumber: "Unexpected addition of a dimension or percentage with a number.", UnexpectedSubtractionOfDimensionOrPercentageWithNumber: "Unexpected subtraction of a dimension or percentage with a number." }, M2 = /[A-Z]/g;
function toLowerCaseAZ(e3) {
  return e3.replace(M2, (e4) => String.fromCharCode(e4.charCodeAt(0) + 32));
}
var T = { cm: "px", in: "px", mm: "px", pc: "px", pt: "px", px: "px", q: "px", deg: "deg", grad: "deg", rad: "deg", turn: "deg", ms: "s", s: "s", hz: "hz", khz: "hz" }, x = /* @__PURE__ */ new Map([["cm", (e3) => e3], ["mm", (e3) => 10 * e3], ["q", (e3) => 40 * e3], ["in", (e3) => e3 / 2.54], ["pc", (e3) => e3 / 2.54 * 6], ["pt", (e3) => e3 / 2.54 * 72], ["px", (e3) => e3 / 2.54 * 96]]), P = /* @__PURE__ */ new Map([["deg", (e3) => e3], ["grad", (e3) => e3 / 0.9], ["rad", (e3) => e3 / 180 * Math.PI], ["turn", (e3) => e3 / 360]]), k = /* @__PURE__ */ new Map([["deg", (e3) => 0.9 * e3], ["grad", (e3) => e3], ["rad", (e3) => 0.9 * e3 / 180 * Math.PI], ["turn", (e3) => 0.9 * e3 / 360]]), O = /* @__PURE__ */ new Map([["hz", (e3) => e3], ["khz", (e3) => e3 / 1e3]]), W = /* @__PURE__ */ new Map([["cm", (e3) => 2.54 * e3], ["mm", (e3) => 25.4 * e3], ["q", (e3) => 25.4 * e3 * 4], ["in", (e3) => e3], ["pc", (e3) => 6 * e3], ["pt", (e3) => 72 * e3], ["px", (e3) => 96 * e3]]), U = /* @__PURE__ */ new Map([["hz", (e3) => 1e3 * e3], ["khz", (e3) => e3]]), L = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 10], ["mm", (e3) => e3], ["q", (e3) => 4 * e3], ["in", (e3) => e3 / 25.4], ["pc", (e3) => e3 / 25.4 * 6], ["pt", (e3) => e3 / 25.4 * 72], ["px", (e3) => e3 / 25.4 * 96]]), V = /* @__PURE__ */ new Map([["ms", (e3) => e3], ["s", (e3) => e3 / 1e3]]), $ = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 6 * 2.54], ["mm", (e3) => e3 / 6 * 25.4], ["q", (e3) => e3 / 6 * 25.4 * 4], ["in", (e3) => e3 / 6], ["pc", (e3) => e3], ["pt", (e3) => e3 / 6 * 72], ["px", (e3) => e3 / 6 * 96]]), Z2 = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 72 * 2.54], ["mm", (e3) => e3 / 72 * 25.4], ["q", (e3) => e3 / 72 * 25.4 * 4], ["in", (e3) => e3 / 72], ["pc", (e3) => e3 / 72 * 6], ["pt", (e3) => e3], ["px", (e3) => e3 / 72 * 96]]), z = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 96 * 2.54], ["mm", (e3) => e3 / 96 * 25.4], ["q", (e3) => e3 / 96 * 25.4 * 4], ["in", (e3) => e3 / 96], ["pc", (e3) => e3 / 96 * 6], ["pt", (e3) => e3 / 96 * 72], ["px", (e3) => e3]]), q = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 4 / 10], ["mm", (e3) => e3 / 4], ["q", (e3) => e3], ["in", (e3) => e3 / 4 / 25.4], ["pc", (e3) => e3 / 4 / 25.4 * 6], ["pt", (e3) => e3 / 4 / 25.4 * 72], ["px", (e3) => e3 / 4 / 25.4 * 96]]), G = /* @__PURE__ */ new Map([["deg", (e3) => 180 * e3 / Math.PI], ["grad", (e3) => 180 * e3 / Math.PI / 0.9], ["rad", (e3) => e3], ["turn", (e3) => 180 * e3 / Math.PI / 360]]), R = /* @__PURE__ */ new Map([["ms", (e3) => 1e3 * e3], ["s", (e3) => e3]]), j = /* @__PURE__ */ new Map([["deg", (e3) => 360 * e3], ["grad", (e3) => 360 * e3 / 0.9], ["rad", (e3) => 360 * e3 / 180 * Math.PI], ["turn", (e3) => e3]]), Y2 = /* @__PURE__ */ new Map([["cm", x], ["mm", L], ["q", q], ["in", W], ["pc", $], ["pt", Z2], ["px", z], ["ms", V], ["s", R], ["deg", P], ["grad", k], ["rad", G], ["turn", j], ["hz", O], ["khz", U]]);
function convertUnit(e3, n3) {
  if (!isTokenDimension(e3)) return n3;
  if (!isTokenDimension(n3)) return n3;
  const t3 = toLowerCaseAZ(e3[4].unit), r3 = toLowerCaseAZ(n3[4].unit);
  if (t3 === r3) return n3;
  const a3 = Y2.get(r3);
  if (!a3) return n3;
  const u3 = a3.get(t3);
  if (!u3) return n3;
  const o3 = u3(n3[4].value), i3 = [c.Dimension, "", n3[2], n3[3], { ...n3[4], signCharacter: o3 < 0 ? "-" : void 0, type: Number.isInteger(o3) ? a.Integer : a.Number, value: o3 }];
  return mutateUnit(i3, e3[4].unit), i3;
}
function toCanonicalUnit(e3) {
  if (!isTokenDimension(e3)) return e3;
  const n3 = toLowerCaseAZ(e3[4].unit), t3 = T[n3];
  if (n3 === t3) return e3;
  const r3 = Y2.get(n3);
  if (!r3) return e3;
  const a3 = r3.get(t3);
  if (!a3) return e3;
  const u3 = a3(e3[4].value), o3 = [c.Dimension, "", e3[2], e3[3], { ...e3[4], signCharacter: u3 < 0 ? "-" : void 0, type: Number.isInteger(u3) ? a.Integer : a.Number, value: u3 }];
  return mutateUnit(o3, t3), o3;
}
function addition(e3, t3) {
  if (2 !== e3.length) return -1;
  const r3 = e3[0].value;
  let a3 = e3[1].value;
  if (isTokenNumber(r3) && isTokenNumber(a3)) {
    const e4 = r3[4].value + a3[4].value;
    return new TokenNode([c.Number, e4.toString(), r3[2], a3[3], { value: e4, type: r3[4].type === a.Integer && a3[4].type === a.Integer ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(r3) && isTokenPercentage(a3)) {
    const e4 = r3[4].value + a3[4].value;
    return new TokenNode([c.Percentage, e4.toString() + "%", r3[2], a3[3], { value: e4 }]);
  }
  if (isTokenDimension(r3) && isTokenDimension(a3) && (a3 = convertUnit(r3, a3), toLowerCaseAZ(r3[4].unit) === toLowerCaseAZ(a3[4].unit))) {
    const e4 = r3[4].value + a3[4].value;
    return new TokenNode([c.Dimension, e4.toString() + r3[4].unit, r3[2], a3[3], { value: e4, type: r3[4].type === a.Integer && a3[4].type === a.Integer ? a.Integer : a.Number, unit: r3[4].unit }]);
  }
  return (isTokenNumber(r3) && (isTokenDimension(a3) || isTokenPercentage(a3)) || isTokenNumber(a3) && (isTokenDimension(r3) || isTokenPercentage(r3))) && t3.onParseError?.(new ParseErrorWithComponentValues(y.UnexpectedAdditionOfDimensionOrPercentageWithNumber, e3)), -1;
}
function division(e3) {
  if (2 !== e3.length) return -1;
  const t3 = e3[0].value, r3 = e3[1].value;
  if (isTokenNumber(t3) && isTokenNumber(r3)) {
    const e4 = t3[4].value / r3[4].value;
    return new TokenNode([c.Number, e4.toString(), t3[2], r3[3], { value: e4, type: Number.isInteger(e4) ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(t3) && isTokenNumber(r3)) {
    const e4 = t3[4].value / r3[4].value;
    return new TokenNode([c.Percentage, e4.toString() + "%", t3[2], r3[3], { value: e4 }]);
  }
  if (isTokenDimension(t3) && isTokenNumber(r3)) {
    const e4 = t3[4].value / r3[4].value;
    return new TokenNode([c.Dimension, e4.toString() + t3[4].unit, t3[2], r3[3], { value: e4, type: Number.isInteger(e4) ? a.Integer : a.Number, unit: t3[4].unit }]);
  }
  return -1;
}
function isCalculation(e3) {
  return !!e3 && "object" == typeof e3 && "inputs" in e3 && Array.isArray(e3.inputs) && "operation" in e3;
}
function solve(e3, n3) {
  if (-1 === e3) return -1;
  const r3 = [];
  for (let a3 = 0; a3 < e3.inputs.length; a3++) {
    const u3 = e3.inputs[a3];
    if (isTokenNode(u3)) {
      r3.push(u3);
      continue;
    }
    const o3 = solve(u3, n3);
    if (-1 === o3) return -1;
    r3.push(o3);
  }
  return e3.operation(r3, n3);
}
function multiplication(e3) {
  if (2 !== e3.length) return -1;
  const t3 = e3[0].value, r3 = e3[1].value;
  if (isTokenNumber(t3) && isTokenNumber(r3)) {
    const e4 = t3[4].value * r3[4].value;
    return new TokenNode([c.Number, e4.toString(), t3[2], r3[3], { value: e4, type: t3[4].type === a.Integer && r3[4].type === a.Integer ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(t3) && isTokenNumber(r3)) {
    const e4 = t3[4].value * r3[4].value;
    return new TokenNode([c.Percentage, e4.toString() + "%", t3[2], r3[3], { value: e4 }]);
  }
  if (isTokenNumber(t3) && isTokenPercentage(r3)) {
    const e4 = t3[4].value * r3[4].value;
    return new TokenNode([c.Percentage, e4.toString() + "%", t3[2], r3[3], { value: e4 }]);
  }
  if (isTokenDimension(t3) && isTokenNumber(r3)) {
    const e4 = t3[4].value * r3[4].value;
    return new TokenNode([c.Dimension, e4.toString() + t3[4].unit, t3[2], r3[3], { value: e4, type: t3[4].type === a.Integer && r3[4].type === a.Integer ? a.Integer : a.Number, unit: t3[4].unit }]);
  }
  if (isTokenNumber(t3) && isTokenDimension(r3)) {
    const e4 = t3[4].value * r3[4].value;
    return new TokenNode([c.Dimension, e4.toString() + r3[4].unit, t3[2], r3[3], { value: e4, type: t3[4].type === a.Integer && r3[4].type === a.Integer ? a.Integer : a.Number, unit: r3[4].unit }]);
  }
  return -1;
}
function resolveGlobalsAndConstants(e3, r3) {
  for (let a3 = 0; a3 < e3.length; a3++) {
    const u3 = e3[a3];
    if (!isTokenNode(u3)) continue;
    const o3 = u3.value;
    if (!isTokenIdent(o3)) continue;
    const i3 = toLowerCaseAZ(o3[4].value);
    switch (i3) {
      case "e":
        e3.splice(a3, 1, new TokenNode([c.Number, Math.E.toString(), o3[2], o3[3], { value: Math.E, type: a.Number }]));
        break;
      case "pi":
        e3.splice(a3, 1, new TokenNode([c.Number, Math.PI.toString(), o3[2], o3[3], { value: Math.PI, type: a.Number }]));
        break;
      case "infinity":
        e3.splice(a3, 1, new TokenNode([c.Number, "infinity", o3[2], o3[3], { value: 1 / 0, type: a.Number }]));
        break;
      case "-infinity":
        e3.splice(a3, 1, new TokenNode([c.Number, "-infinity", o3[2], o3[3], { value: -1 / 0, type: a.Number }]));
        break;
      case "nan":
        e3.splice(a3, 1, new TokenNode([c.Number, "NaN", o3[2], o3[3], { value: Number.NaN, type: a.Number }]));
        break;
      default:
        if (r3.has(i3)) {
          const t3 = r3.get(i3);
          e3.splice(a3, 1, new TokenNode(t3));
        }
    }
  }
  return e3;
}
function unary(e3) {
  if (1 !== e3.length) return -1;
  const n3 = e3[0].value;
  return isTokenNumeric(n3) ? e3[0] : -1;
}
function resultToCalculation(e3, n3, t3) {
  return isTokenDimension(n3) ? dimensionToCalculation(e3, n3[4].unit, t3) : isTokenPercentage(n3) ? percentageToCalculation(e3, t3) : isTokenNumber(n3) ? numberToCalculation(e3, t3) : -1;
}
function dimensionToCalculation(e3, t3, r3) {
  const a3 = e3.tokens();
  return { inputs: [new TokenNode([c.Dimension, r3.toString() + t3, a3[0][2], a3[a3.length - 1][3], { value: r3, type: Number.isInteger(r3) ? a.Integer : a.Number, unit: t3 }])], operation: unary };
}
function percentageToCalculation(e3, t3) {
  const r3 = e3.tokens();
  return { inputs: [new TokenNode([c.Percentage, t3.toString() + "%", r3[0][2], r3[r3.length - 1][3], { value: t3 }])], operation: unary };
}
function numberToCalculation(e3, t3) {
  const r3 = e3.tokens();
  return { inputs: [new TokenNode([c.Number, t3.toString(), r3[0][2], r3[r3.length - 1][3], { value: t3, type: Number.isInteger(t3) ? a.Integer : a.Number }])], operation: unary };
}
function solveACos(e3, n3) {
  const t3 = n3.value;
  if (!isTokenNumber(t3)) return -1;
  return dimensionToCalculation(e3, "rad", Math.acos(t3[4].value));
}
function solveASin(e3, n3) {
  const t3 = n3.value;
  if (!isTokenNumber(t3)) return -1;
  return dimensionToCalculation(e3, "rad", Math.asin(t3[4].value));
}
function solveATan(e3, n3) {
  const t3 = n3.value;
  if (!isTokenNumber(t3)) return -1;
  return dimensionToCalculation(e3, "rad", Math.atan(t3[4].value));
}
function isDimensionOrNumber(e3) {
  return isTokenDimension(e3) || isTokenNumber(e3);
}
function arrayOfSameNumeric(e3) {
  if (0 === e3.length) return true;
  const n3 = e3[0];
  if (!isTokenNumeric(n3)) return false;
  if (1 === e3.length) return true;
  if (isTokenDimension(n3)) {
    const t3 = toLowerCaseAZ(n3[4].unit);
    for (let r3 = 1; r3 < e3.length; r3++) {
      const a3 = e3[r3];
      if (n3[0] !== a3[0]) return false;
      if (t3 !== toLowerCaseAZ(a3[4].unit)) return false;
    }
    return true;
  }
  for (let t3 = 1; t3 < e3.length; t3++) {
    const r3 = e3[t3];
    if (n3[0] !== r3[0]) return false;
  }
  return true;
}
function twoOfSameNumeric(e3, n3) {
  return !!isTokenNumeric(e3) && (isTokenDimension(e3) ? e3[0] === n3[0] && toLowerCaseAZ(e3[4].unit) === toLowerCaseAZ(n3[4].unit) : e3[0] === n3[0]);
}
function solveATan2(e3, n3, t3) {
  const r3 = n3.value;
  if (!isDimensionOrNumber(r3)) return -1;
  const a3 = convertUnit(r3, t3.value);
  if (!twoOfSameNumeric(r3, a3)) return -1;
  return dimensionToCalculation(e3, "rad", Math.atan2(r3[4].value, a3[4].value));
}
function solveAbs(e3, n3, t3) {
  const r3 = n3.value;
  if (!isTokenNumeric(r3)) return -1;
  if (!t3.rawPercentages && isTokenPercentage(r3)) return -1;
  return resultToCalculation(e3, r3, Math.abs(r3[4].value));
}
function solveClamp(e3, n3, r3, a3, u3) {
  if (!isTokenNode(n3) || !isTokenNode(r3) || !isTokenNode(a3)) return -1;
  const o3 = n3.value;
  if (!isTokenNumeric(o3)) return -1;
  if (!u3.rawPercentages && isTokenPercentage(o3)) return -1;
  const i3 = convertUnit(o3, r3.value);
  if (!twoOfSameNumeric(o3, i3)) return -1;
  const l2 = convertUnit(o3, a3.value);
  if (!twoOfSameNumeric(o3, l2)) return -1;
  return resultToCalculation(e3, o3, Math.max(o3[4].value, Math.min(i3[4].value, l2[4].value)));
}
function solveCos(e3, n3) {
  const t3 = n3.value;
  if (!isDimensionOrNumber(t3)) return -1;
  let r3 = t3[4].value;
  if (isTokenDimension(t3)) switch (t3[4].unit.toLowerCase()) {
    case "rad":
      break;
    case "deg":
      r3 = P.get("rad")(t3[4].value);
      break;
    case "grad":
      r3 = k.get("rad")(t3[4].value);
      break;
    case "turn":
      r3 = j.get("rad")(t3[4].value);
      break;
    default:
      return -1;
  }
  return r3 = Math.cos(r3), numberToCalculation(e3, r3);
}
function solveExp(e3, n3) {
  const t3 = n3.value;
  if (!isTokenNumber(t3)) return -1;
  return numberToCalculation(e3, Math.exp(t3[4].value));
}
function solveHypot(e3, n3, r3) {
  if (!n3.every(isTokenNode)) return -1;
  const a3 = n3[0].value;
  if (!isTokenNumeric(a3)) return -1;
  if (!r3.rawPercentages && isTokenPercentage(a3)) return -1;
  const u3 = n3.map((e4) => convertUnit(a3, e4.value));
  if (!arrayOfSameNumeric(u3)) return -1;
  const o3 = u3.map((e4) => e4[4].value), i3 = Math.hypot(...o3);
  return resultToCalculation(e3, a3, i3);
}
function solveMax(e3, n3, r3) {
  if (!n3.every(isTokenNode)) return -1;
  const a3 = n3[0].value;
  if (!isTokenNumeric(a3)) return -1;
  if (!r3.rawPercentages && isTokenPercentage(a3)) return -1;
  const u3 = n3.map((e4) => convertUnit(a3, e4.value));
  if (!arrayOfSameNumeric(u3)) return -1;
  const o3 = u3.map((e4) => e4[4].value), i3 = Math.max(...o3);
  return resultToCalculation(e3, a3, i3);
}
function solveMin(e3, n3, r3) {
  if (!n3.every(isTokenNode)) return -1;
  const a3 = n3[0].value;
  if (!isTokenNumeric(a3)) return -1;
  if (!r3.rawPercentages && isTokenPercentage(a3)) return -1;
  const u3 = n3.map((e4) => convertUnit(a3, e4.value));
  if (!arrayOfSameNumeric(u3)) return -1;
  const o3 = u3.map((e4) => e4[4].value), i3 = Math.min(...o3);
  return resultToCalculation(e3, a3, i3);
}
function solveMod(e3, n3, t3) {
  const r3 = n3.value;
  if (!isTokenNumeric(r3)) return -1;
  const a3 = convertUnit(r3, t3.value);
  if (!twoOfSameNumeric(r3, a3)) return -1;
  let u3;
  return u3 = 0 === a3[4].value ? Number.NaN : Number.isFinite(r3[4].value) && (Number.isFinite(a3[4].value) || (a3[4].value !== Number.POSITIVE_INFINITY || r3[4].value !== Number.NEGATIVE_INFINITY && !Object.is(0 * r3[4].value, -0)) && (a3[4].value !== Number.NEGATIVE_INFINITY || r3[4].value !== Number.POSITIVE_INFINITY && !Object.is(0 * r3[4].value, 0))) ? Number.isFinite(a3[4].value) ? (r3[4].value % a3[4].value + a3[4].value) % a3[4].value : r3[4].value : Number.NaN, resultToCalculation(e3, r3, u3);
}
function solvePow(e3, n3, t3) {
  const r3 = n3.value, a3 = t3.value;
  if (!isTokenNumber(r3)) return -1;
  if (!twoOfSameNumeric(r3, a3)) return -1;
  return numberToCalculation(e3, Math.pow(r3[4].value, a3[4].value));
}
function solveRem(e3, n3, t3) {
  const r3 = n3.value;
  if (!isTokenNumeric(r3)) return -1;
  const a3 = convertUnit(r3, t3.value);
  if (!twoOfSameNumeric(r3, a3)) return -1;
  let u3;
  return u3 = 0 === a3[4].value ? Number.NaN : Number.isFinite(r3[4].value) ? Number.isFinite(a3[4].value) ? r3[4].value % a3[4].value : r3[4].value : Number.NaN, resultToCalculation(e3, r3, u3);
}
function solveRound(e3, n3, t3, r3, a3) {
  const u3 = t3.value;
  if (!isTokenNumeric(u3)) return -1;
  if (!a3.rawPercentages && isTokenPercentage(u3)) return -1;
  const o3 = convertUnit(u3, r3.value);
  if (!twoOfSameNumeric(u3, o3)) return -1;
  let i3;
  if (0 === o3[4].value) i3 = Number.NaN;
  else if (Number.isFinite(u3[4].value) || Number.isFinite(o3[4].value)) if (!Number.isFinite(u3[4].value) && Number.isFinite(o3[4].value)) i3 = u3[4].value;
  else if (Number.isFinite(u3[4].value) && !Number.isFinite(o3[4].value)) switch (n3) {
    case "down":
      i3 = u3[4].value < 0 ? -1 / 0 : Object.is(-0, 0 * u3[4].value) ? -0 : 0;
      break;
    case "up":
      i3 = u3[4].value > 0 ? 1 / 0 : Object.is(0, 0 * u3[4].value) ? 0 : -0;
      break;
    default:
      i3 = Object.is(0, 0 * u3[4].value) ? 0 : -0;
  }
  else if (Number.isFinite(o3[4].value)) switch (n3) {
    case "down":
      i3 = Math.floor(u3[4].value / o3[4].value) * o3[4].value;
      break;
    case "up":
      i3 = Math.ceil(u3[4].value / o3[4].value) * o3[4].value;
      break;
    case "to-zero":
      i3 = Math.trunc(u3[4].value / o3[4].value) * o3[4].value;
      break;
    default: {
      let e4 = Math.floor(u3[4].value / o3[4].value) * o3[4].value, n4 = Math.ceil(u3[4].value / o3[4].value) * o3[4].value;
      if (e4 > n4) {
        const t5 = e4;
        e4 = n4, n4 = t5;
      }
      const t4 = Math.abs(u3[4].value - e4), r4 = Math.abs(u3[4].value - n4);
      i3 = t4 === r4 ? n4 : t4 < r4 ? e4 : n4;
      break;
    }
  }
  else i3 = u3[4].value;
  else i3 = Number.NaN;
  return resultToCalculation(e3, u3, i3);
}
function solveSign(e3, n3, t3) {
  const r3 = n3.value;
  if (!isTokenNumeric(r3)) return -1;
  if (!t3.rawPercentages && isTokenPercentage(r3)) return -1;
  return numberToCalculation(e3, Math.sign(r3[4].value));
}
function solveSin(e3, n3) {
  const t3 = n3.value;
  if (!isDimensionOrNumber(t3)) return -1;
  let r3 = t3[4].value;
  if (isTokenDimension(t3)) switch (toLowerCaseAZ(t3[4].unit)) {
    case "rad":
      break;
    case "deg":
      r3 = P.get("rad")(t3[4].value);
      break;
    case "grad":
      r3 = k.get("rad")(t3[4].value);
      break;
    case "turn":
      r3 = j.get("rad")(t3[4].value);
      break;
    default:
      return -1;
  }
  return r3 = Math.sin(r3), numberToCalculation(e3, r3);
}
function solveSqrt(e3, n3) {
  const t3 = n3.value;
  if (!isTokenNumber(t3)) return -1;
  return numberToCalculation(e3, Math.sqrt(t3[4].value));
}
function solveTan(e3, n3) {
  const t3 = n3.value;
  if (!isDimensionOrNumber(t3)) return -1;
  const r3 = t3[4].value;
  let a3 = 0, u3 = t3[4].value;
  if (isTokenDimension(t3)) switch (toLowerCaseAZ(t3[4].unit)) {
    case "rad":
      a3 = G.get("deg")(r3);
      break;
    case "deg":
      a3 = r3, u3 = P.get("rad")(r3);
      break;
    case "grad":
      a3 = k.get("deg")(r3), u3 = k.get("rad")(r3);
      break;
    case "turn":
      a3 = j.get("deg")(r3), u3 = j.get("rad")(r3);
      break;
    default:
      return -1;
  }
  const o3 = a3 / 90;
  return u3 = a3 % 90 == 0 && o3 % 2 != 0 ? o3 > 0 ? 1 / 0 : -1 / 0 : Math.tan(u3), numberToCalculation(e3, u3);
}
function subtraction(e3, t3) {
  if (2 !== e3.length) return -1;
  const r3 = e3[0].value;
  let a3 = e3[1].value;
  if (isTokenNumber(r3) && isTokenNumber(a3)) {
    const e4 = r3[4].value - a3[4].value;
    return new TokenNode([c.Number, e4.toString(), r3[2], a3[3], { value: e4, type: r3[4].type === a.Integer && a3[4].type === a.Integer ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(r3) && isTokenPercentage(a3)) {
    const e4 = r3[4].value - a3[4].value;
    return new TokenNode([c.Percentage, e4.toString() + "%", r3[2], a3[3], { value: e4 }]);
  }
  if (isTokenDimension(r3) && isTokenDimension(a3) && (a3 = convertUnit(r3, a3), toLowerCaseAZ(r3[4].unit) === toLowerCaseAZ(a3[4].unit))) {
    const e4 = r3[4].value - a3[4].value;
    return new TokenNode([c.Dimension, e4.toString() + r3[4].unit, r3[2], a3[3], { value: e4, type: r3[4].type === a.Integer && a3[4].type === a.Integer ? a.Integer : a.Number, unit: r3[4].unit }]);
  }
  return (isTokenNumber(r3) && (isTokenDimension(a3) || isTokenPercentage(a3)) || isTokenNumber(a3) && (isTokenDimension(r3) || isTokenPercentage(r3))) && t3.onParseError?.(new ParseErrorWithComponentValues(y.UnexpectedSubtractionOfDimensionOrPercentageWithNumber, e3)), -1;
}
function solveLog(e3, n3) {
  if (1 === n3.length) {
    const r3 = n3[0];
    if (!r3 || !isTokenNode(r3)) return -1;
    const a3 = r3.value;
    if (!isTokenNumber(a3)) return -1;
    return numberToCalculation(e3, Math.log(a3[4].value));
  }
  if (2 === n3.length) {
    const r3 = n3[0];
    if (!r3 || !isTokenNode(r3)) return -1;
    const a3 = r3.value;
    if (!isTokenNumber(a3)) return -1;
    const u3 = n3[1];
    if (!u3 || !isTokenNode(u3)) return -1;
    const o3 = u3.value;
    if (!isTokenNumber(o3)) return -1;
    return numberToCalculation(e3, Math.log(a3[4].value) / Math.log(o3[4].value));
  }
  return -1;
}
var _2 = /^none$/i;
function isNone(e3) {
  if (Array.isArray(e3)) {
    const n4 = e3.filter((e4) => !(isWhitespaceNode(e4) && isCommentNode(e4)));
    return 1 === n4.length && isNone(n4[0]);
  }
  if (!isTokenNode(e3)) return false;
  const n3 = e3.value;
  return !!isTokenIdent(n3) && _2.test(n3[4].value);
}
var H = String.fromCodePoint(0);
function solveRandom(e3, n3, t3, r3, a3, u3) {
  if (-1 === n3.fixed && !u3.randomCaching) return -1;
  u3.randomCaching || (u3.randomCaching = { propertyName: "", propertyN: 0, elementID: "", documentID: "" }), u3.randomCaching && !u3.randomCaching.propertyN && (u3.randomCaching.propertyN = 0);
  const o3 = t3.value;
  if (!isTokenNumeric(o3)) return -1;
  const i3 = convertUnit(o3, r3.value);
  if (!twoOfSameNumeric(o3, i3)) return -1;
  let l2 = null;
  if (a3 && (l2 = convertUnit(o3, a3.value), !twoOfSameNumeric(o3, l2))) return -1;
  if (!Number.isFinite(o3[4].value)) return resultToCalculation(e3, o3, Number.NaN);
  if (!Number.isFinite(i3[4].value)) return resultToCalculation(e3, o3, Number.NaN);
  if (!Number.isFinite(i3[4].value - o3[4].value)) return resultToCalculation(e3, o3, Number.NaN);
  if (l2 && !Number.isFinite(l2[4].value)) return resultToCalculation(e3, o3, o3[4].value);
  const c3 = -1 === n3.fixed ? sfc32(crc32([n3.dashedIdent ? n3.dashedIdent : `${u3.randomCaching?.propertyName} ${u3.randomCaching.propertyN++}`, n3.elementShared ? "" : u3.randomCaching.elementID, u3.randomCaching.documentID].join(H))) : () => n3.fixed;
  let s3 = o3[4].value, v = i3[4].value;
  if (s3 > v && ([s3, v] = [v, s3]), l2 && (l2[4].value <= 0 || Math.abs(s3 - v) / l2[4].value > 1e10) && (l2 = null), l2) {
    const n4 = Math.max(l2[4].value / 1e3, 1e-9), t4 = [s3];
    let r4 = 0;
    for (; ; ) {
      r4 += l2[4].value;
      const e4 = s3 + r4;
      if (!(e4 + n4 < v)) {
        t4.push(v);
        break;
      }
      if (t4.push(e4), e4 + l2[4].value - n4 > v) break;
    }
    const a4 = c3();
    return resultToCalculation(e3, o3, Number(t4[Math.floor(t4.length * a4)].toFixed(5)));
  }
  const f3 = c3();
  return resultToCalculation(e3, o3, Number((f3 * (v - s3) + s3).toFixed(5)));
}
function sfc32(e3 = 0.34944106645296036, n3 = 0.19228640875738723, t3 = 0.8784393832007205, r3 = 0.04850964319275053) {
  return () => {
    const a3 = ((e3 |= 0) + (n3 |= 0) | 0) + (r3 |= 0) | 0;
    return r3 = r3 + 1 | 0, e3 = n3 ^ n3 >>> 9, n3 = (t3 |= 0) + (t3 << 3) | 0, t3 = (t3 = t3 << 21 | t3 >>> 11) + a3 | 0, (a3 >>> 0) / 4294967296;
  };
}
function crc32(e3) {
  let n3 = 0, t3 = 0, r3 = 0;
  n3 ^= -1;
  for (let a3 = 0, u3 = e3.length; a3 < u3; a3++) r3 = 255 & (n3 ^ e3.charCodeAt(a3)), t3 = Number("0x" + "00000000 77073096 EE0E612C 990951BA 076DC419 706AF48F E963A535 9E6495A3 0EDB8832 79DCB8A4 E0D5E91E 97D2D988 09B64C2B 7EB17CBD E7B82D07 90BF1D91 1DB71064 6AB020F2 F3B97148 84BE41DE 1ADAD47D 6DDDE4EB F4D4B551 83D385C7 136C9856 646BA8C0 FD62F97A 8A65C9EC 14015C4F 63066CD9 FA0F3D63 8D080DF5 3B6E20C8 4C69105E D56041E4 A2677172 3C03E4D1 4B04D447 D20D85FD A50AB56B 35B5A8FA 42B2986C DBBBC9D6 ACBCF940 32D86CE3 45DF5C75 DCD60DCF ABD13D59 26D930AC 51DE003A C8D75180 BFD06116 21B4F4B5 56B3C423 CFBA9599 B8BDA50F 2802B89E 5F058808 C60CD9B2 B10BE924 2F6F7C87 58684C11 C1611DAB B6662D3D 76DC4190 01DB7106 98D220BC EFD5102A 71B18589 06B6B51F 9FBFE4A5 E8B8D433 7807C9A2 0F00F934 9609A88E E10E9818 7F6A0DBB 086D3D2D 91646C97 E6635C01 6B6B51F4 1C6C6162 856530D8 F262004E 6C0695ED 1B01A57B 8208F4C1 F50FC457 65B0D9C6 12B7E950 8BBEB8EA FCB9887C 62DD1DDF 15DA2D49 8CD37CF3 FBD44C65 4DB26158 3AB551CE A3BC0074 D4BB30E2 4ADFA541 3DD895D7 A4D1C46D D3D6F4FB 4369E96A 346ED9FC AD678846 DA60B8D0 44042D73 33031DE5 AA0A4C5F DD0D7CC9 5005713C 270241AA BE0B1010 C90C2086 5768B525 206F85B3 B966D409 CE61E49F 5EDEF90E 29D9C998 B0D09822 C7D7A8B4 59B33D17 2EB40D81 B7BD5C3B C0BA6CAD EDB88320 9ABFB3B6 03B6E20C 74B1D29A EAD54739 9DD277AF 04DB2615 73DC1683 E3630B12 94643B84 0D6D6A3E 7A6A5AA8 E40ECF0B 9309FF9D 0A00AE27 7D079EB1 F00F9344 8708A3D2 1E01F268 6906C2FE F762575D 806567CB 196C3671 6E6B06E7 FED41B76 89D32BE0 10DA7A5A 67DD4ACC F9B9DF6F 8EBEEFF9 17B7BE43 60B08ED5 D6D6A3E8 A1D1937E 38D8C2C4 4FDFF252 D1BB67F1 A6BC5767 3FB506DD 48B2364B D80D2BDA AF0A1B4C 36034AF6 41047A60 DF60EFC3 A867DF55 316E8EEF 4669BE79 CB61B38C BC66831A 256FD2A0 5268E236 CC0C7795 BB0B4703 220216B9 5505262F C5BA3BBE B2BD0B28 2BB45A92 5CB36A04 C2D7FFA7 B5D0CF31 2CD99E8B 5BDEAE1D 9B64C2B0 EC63F226 756AA39C 026D930A 9C0906A9 EB0E363F 72076785 05005713 95BF4A82 E2B87A14 7BB12BAE 0CB61B38 92D28E9B E5D5BE0D 7CDCEFB7 0BDBDF21 86D3D2D4 F1D4E242 68DDB3F8 1FDA836E 81BE16CD F6B9265B 6FB077E1 18B74777 88085AE6 FF0F6A70 66063BCA 11010B5C 8F659EFF F862AE69 616BFFD3 166CCF45 A00AE278 D70DD2EE 4E048354 3903B3C2 A7672661 D06016F7 4969474D 3E6E77DB AED16A4A D9D65ADC 40DF0B66 37D83BF0 A9BCAE53 DEBB9EC5 47B2CF7F 30B5FFE9 BDBDF21C CABAC28A 53B39330 24B4A3A6 BAD03605 CDD70693 54DE5729 23D967BF B3667A2E C4614AB8 5D681B02 2A6F2B94 B40BBE37 C30C8EA1 5A05DF1B 2D02EF8D".substring(9 * r3, 9 * r3 + 8)), n3 = n3 >>> 8 ^ t3;
  return (-1 ^ n3) >>> 0;
}
var J = /* @__PURE__ */ new Map([["abs", function abs(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveAbs);
}], ["acos", function acos(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveACos);
}], ["asin", function asin(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveASin);
}], ["atan", function atan(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveATan);
}], ["atan2", function atan2(e3, n3, t3) {
  return twoCommaSeparatedNodesSolver(e3, n3, t3, solveATan2);
}], ["calc", calc$1], ["clamp", function clamp(r3, a3, o3) {
  const i3 = resolveGlobalsAndConstants([...r3.value.filter((e3) => !isWhiteSpaceOrCommentNode(e3))], a3), c3 = [], s3 = [], v = [];
  {
    let e3 = c3;
    for (let n3 = 0; n3 < i3.length; n3++) {
      const r4 = i3[n3];
      if (isTokenNode(r4) && isTokenComma(r4.value)) {
        if (e3 === v) return -1;
        if (e3 === s3) {
          e3 = v;
          continue;
        }
        if (e3 === c3) {
          e3 = s3;
          continue;
        }
        return -1;
      }
      e3.push(r4);
    }
  }
  const f3 = isNone(c3), p2 = isNone(v);
  if (f3 && p2) return calc$1(calcWrapper(r3, s3), a3, o3);
  const C = solve(calc$1(calcWrapper(r3, s3), a3, o3), o3);
  if (-1 === C) return -1;
  if (f3) {
    const t3 = solve(calc$1(calcWrapper(r3, v), a3, o3), o3);
    return -1 === t3 ? -1 : solveMin((d3 = r3, g2 = C, D2 = t3, new FunctionNode([c.Function, "min(", d3.name[2], d3.name[3], { value: "min" }], [c.CloseParen, ")", d3.endToken[2], d3.endToken[3], void 0], [g2, new TokenNode([c.Comma, ",", ...sourceIndices(g2), void 0]), D2])), [C, t3], o3);
  }
  if (p2) {
    const e3 = solve(calc$1(calcWrapper(r3, c3), a3, o3), o3);
    return -1 === e3 ? -1 : solveMax(maxWrapper(r3, e3, C), [e3, C], o3);
  }
  var d3, g2, D2;
  const N = solve(calc$1(calcWrapper(r3, c3), a3, o3), o3);
  if (-1 === N) return -1;
  const h2 = solve(calc$1(calcWrapper(r3, v), a3, o3), o3);
  if (-1 === h2) return -1;
  return solveClamp(r3, N, C, h2, o3);
}], ["cos", function cos(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveCos);
}], ["exp", function exp(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveExp);
}], ["hypot", function hypot(e3, n3, t3) {
  return variadicNodesSolver(e3, n3, t3, solveHypot);
}], ["log", function log(e3, n3, t3) {
  return variadicNodesSolver(e3, n3, t3, solveLog);
}], ["max", function max(e3, n3, t3) {
  return variadicNodesSolver(e3, n3, t3, solveMax);
}], ["min", function min(e3, n3, t3) {
  return variadicNodesSolver(e3, n3, t3, solveMin);
}], ["mod", function mod(e3, n3, t3) {
  return twoCommaSeparatedNodesSolver(e3, n3, t3, solveMod);
}], ["pow", function pow(e3, n3, t3) {
  return twoCommaSeparatedNodesSolver(e3, n3, t3, solvePow);
}], ["random", function random(e3, n3, t3) {
  const r3 = parseRandomValueSharing(e3, e3.value.filter((e4) => !isWhiteSpaceOrCommentNode(e4)), n3, t3);
  if (-1 === r3) return -1;
  const [a3, o3] = r3, i3 = variadicArguments(e3, o3, n3, t3);
  if (-1 === i3) return -1;
  const [l2, c3, s3] = i3;
  if (!l2 || !c3) return -1;
  return solveRandom(e3, a3, l2, c3, s3, t3);
}], ["rem", function rem(e3, n3, t3) {
  return twoCommaSeparatedNodesSolver(e3, n3, t3, solveRem);
}], ["round", function round(e3, r3, a3) {
  const o3 = resolveGlobalsAndConstants([...e3.value.filter((e4) => !isWhiteSpaceOrCommentNode(e4))], r3);
  let i3 = "", l2 = false;
  const c3 = [], s3 = [];
  {
    let e4 = c3;
    for (let n3 = 0; n3 < o3.length; n3++) {
      const r4 = o3[n3];
      if (!i3 && 0 === c3.length && 0 === s3.length && isTokenNode(r4) && isTokenIdent(r4.value)) {
        const e5 = r4.value[4].value.toLowerCase();
        if (K.has(e5)) {
          i3 = e5;
          continue;
        }
      }
      if (isTokenNode(r4) && isTokenComma(r4.value)) {
        if (e4 === s3) return -1;
        if (e4 === c3 && i3 && 0 === c3.length) continue;
        if (e4 === c3) {
          l2 = true, e4 = s3;
          continue;
        }
        return -1;
      }
      e4.push(r4);
    }
  }
  const v = solve(calc$1(calcWrapper(e3, c3), r3, a3), a3);
  if (-1 === v) return -1;
  l2 || 0 !== s3.length || s3.push(new TokenNode([c.Number, "1", v.value[2], v.value[3], { value: 1, type: a.Integer }]));
  const f3 = solve(calc$1(calcWrapper(e3, s3), r3, a3), a3);
  if (-1 === f3) return -1;
  i3 || (i3 = "nearest");
  return solveRound(e3, i3, v, f3, a3);
}], ["sign", function sign(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveSign);
}], ["sin", function sin(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveSin);
}], ["sqrt", function sqrt(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveSqrt);
}], ["tan", function tan(e3, n3, t3) {
  return singleNodeSolver(e3, n3, t3, solveTan);
}]]);
function calc$1(e3, n3, r3) {
  const a3 = resolveGlobalsAndConstants([...e3.value.filter((e4) => !isWhiteSpaceOrCommentNode(e4))], n3);
  if (1 === a3.length && isTokenNode(a3[0])) return { inputs: [a3[0]], operation: unary };
  let l2 = 0;
  for (; l2 < a3.length; ) {
    const e4 = a3[l2];
    if (isSimpleBlockNode(e4) && isTokenOpenParen(e4.startToken)) {
      const t3 = calc$1(e4, n3, r3);
      if (-1 === t3) return -1;
      a3.splice(l2, 1, t3);
      continue;
    }
    if (isFunctionNode(e4)) {
      const t3 = J.get(e4.getName().toLowerCase());
      if (!t3) return -1;
      const u3 = t3(e4, n3, r3);
      if (-1 === u3) return -1;
      a3.splice(l2, 1, u3);
      continue;
    }
    l2++;
  }
  if (l2 = 0, 1 === a3.length && isCalculation(a3[0])) return a3[0];
  for (; l2 < a3.length; ) {
    const e4 = a3[l2];
    if (!e4 || !isTokenNode(e4) && !isCalculation(e4)) {
      l2++;
      continue;
    }
    const n4 = a3[l2 + 1];
    if (!n4 || !isTokenNode(n4)) {
      l2++;
      continue;
    }
    const r4 = n4.value;
    if (!isTokenDelim(r4) || "*" !== r4[4].value && "/" !== r4[4].value) {
      l2++;
      continue;
    }
    const u3 = a3[l2 + 2];
    if (!u3 || !isTokenNode(u3) && !isCalculation(u3)) return -1;
    "*" !== r4[4].value ? "/" !== r4[4].value ? l2++ : a3.splice(l2, 3, { inputs: [e4, u3], operation: division }) : a3.splice(l2, 3, { inputs: [e4, u3], operation: multiplication });
  }
  if (l2 = 0, 1 === a3.length && isCalculation(a3[0])) return a3[0];
  for (; l2 < a3.length; ) {
    const e4 = a3[l2];
    if (!e4 || !isTokenNode(e4) && !isCalculation(e4)) {
      l2++;
      continue;
    }
    const n4 = a3[l2 + 1];
    if (!n4 || !isTokenNode(n4)) {
      l2++;
      continue;
    }
    const r4 = n4.value;
    if (!isTokenDelim(r4) || "+" !== r4[4].value && "-" !== r4[4].value) {
      l2++;
      continue;
    }
    const u3 = a3[l2 + 2];
    if (!u3 || !isTokenNode(u3) && !isCalculation(u3)) return -1;
    "+" !== r4[4].value ? "-" !== r4[4].value ? l2++ : a3.splice(l2, 3, { inputs: [e4, u3], operation: subtraction }) : a3.splice(l2, 3, { inputs: [e4, u3], operation: addition });
  }
  return 1 === a3.length && isCalculation(a3[0]) ? a3[0] : -1;
}
function singleNodeSolver(e3, n3, t3, r3) {
  const a3 = singleArgument(e3, n3, t3);
  return -1 === a3 ? -1 : r3(e3, a3, t3);
}
function singleArgument(e3, n3, t3) {
  const r3 = resolveGlobalsAndConstants([...e3.value.filter((e4) => !isWhiteSpaceOrCommentNode(e4))], n3), a3 = solve(calc$1(calcWrapper(e3, r3), n3, t3), t3);
  return -1 === a3 ? -1 : a3;
}
function twoCommaSeparatedNodesSolver(e3, n3, t3, r3) {
  const a3 = twoCommaSeparatedArguments(e3, n3, t3);
  if (-1 === a3) return -1;
  const [u3, o3] = a3;
  return r3(e3, u3, o3, t3);
}
function twoCommaSeparatedArguments(e3, n3, r3) {
  const a3 = resolveGlobalsAndConstants([...e3.value.filter((e4) => !isWhiteSpaceOrCommentNode(e4))], n3), o3 = [], i3 = [];
  {
    let e4 = o3;
    for (let n4 = 0; n4 < a3.length; n4++) {
      const r4 = a3[n4];
      if (isTokenNode(r4) && isTokenComma(r4.value)) {
        if (e4 === i3) return -1;
        if (e4 === o3) {
          e4 = i3;
          continue;
        }
        return -1;
      }
      e4.push(r4);
    }
  }
  const l2 = solve(calc$1(calcWrapper(e3, o3), n3, r3), r3);
  if (-1 === l2) return -1;
  const c3 = solve(calc$1(calcWrapper(e3, i3), n3, r3), r3);
  return -1 === c3 ? -1 : [l2, c3];
}
function variadicNodesSolver(e3, n3, t3, r3) {
  const a3 = variadicArguments(e3, e3.value, n3, t3);
  return -1 === a3 ? -1 : r3(e3, a3, t3);
}
function variadicArguments(e3, n3, r3, a3) {
  const o3 = resolveGlobalsAndConstants([...n3.filter((e4) => !isWhiteSpaceOrCommentNode(e4))], r3), i3 = [];
  {
    const n4 = [];
    let u3 = [];
    for (let e4 = 0; e4 < o3.length; e4++) {
      const r4 = o3[e4];
      isTokenNode(r4) && isTokenComma(r4.value) ? (n4.push(u3), u3 = []) : u3.push(r4);
    }
    n4.push(u3);
    for (let t3 = 0; t3 < n4.length; t3++) {
      if (0 === n4[t3].length) return -1;
      const u4 = solve(calc$1(calcWrapper(e3, n4[t3]), r3, a3), a3);
      if (-1 === u4) return -1;
      i3.push(u4);
    }
  }
  return i3;
}
var K = /* @__PURE__ */ new Set(["nearest", "up", "down", "to-zero"]);
function parseRandomValueSharing(e3, n3, r3, a3) {
  const u3 = { isAuto: false, dashedIdent: "", fixed: -1, elementShared: false }, o3 = n3[0];
  if (!isTokenNode(o3) || !isTokenIdent(o3.value)) return [u3, n3];
  for (let o4 = 0; o4 < n3.length; o4++) {
    const i3 = n3[o4];
    if (!isTokenNode(i3)) return -1;
    if (isTokenComma(i3.value)) return [u3, n3.slice(o4 + 1)];
    if (!isTokenIdent(i3.value)) return -1;
    const l2 = i3.value[4].value.toLowerCase();
    if ("element-shared" !== l2) {
      if ("fixed" === l2) {
        if (u3.elementShared || u3.dashedIdent || u3.isAuto) return -1;
        o4++;
        const t3 = n3[o4];
        if (!t3) return -1;
        const i4 = solve(calc$1(calcWrapper(e3, [t3]), r3, a3), a3);
        if (-1 === i4) return -1;
        if (!isTokenNumber(i4.value)) return -1;
        if (i4.value[4].value < 0 || i4.value[4].value > 1) return -1;
        u3.fixed = Math.max(0, Math.min(i4.value[4].value, 1 - 1e-9));
        continue;
      }
      if ("auto" !== l2) if (l2.startsWith("--")) {
        if (-1 !== u3.fixed || u3.isAuto) return -1;
        u3.dashedIdent = l2;
      } else ;
      else {
        if (-1 !== u3.fixed || u3.dashedIdent) return -1;
        u3.isAuto = true;
      }
    } else {
      if (-1 !== u3.fixed) return -1;
      u3.elementShared = true;
    }
  }
  return -1;
}
function calcWrapper(e3, n3) {
  return new FunctionNode([c.Function, "calc(", e3.name[2], e3.name[3], { value: "calc" }], [c.CloseParen, ")", e3.endToken[2], e3.endToken[3], void 0], n3);
}
function maxWrapper(t3, r3, a3) {
  return new FunctionNode([c.Function, "max(", t3.name[2], t3.name[3], { value: "max" }], [c.CloseParen, ")", t3.endToken[2], t3.endToken[3], void 0], [r3, new TokenNode([c.Comma, ",", ...sourceIndices(r3), void 0]), a3]);
}
function patchNaN(e3) {
  if (-1 === e3) return -1;
  if (isFunctionNode(e3)) return e3;
  const t3 = e3.value;
  return isTokenNumeric(t3) && Number.isNaN(t3[4].value) ? isTokenNumber(t3) ? new FunctionNode([c.Function, "calc(", t3[2], t3[3], { value: "calc" }], [c.CloseParen, ")", t3[2], t3[3], void 0], [new TokenNode([c.Ident, "NaN", t3[2], t3[3], { value: "NaN" }])]) : isTokenDimension(t3) ? new FunctionNode([c.Function, "calc(", t3[2], t3[3], { value: "calc" }], [c.CloseParen, ")", t3[2], t3[3], void 0], [new TokenNode([c.Ident, "NaN", t3[2], t3[3], { value: "NaN" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Delim, "*", t3[2], t3[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Dimension, "1" + t3[4].unit, t3[2], t3[3], { value: 1, type: a.Integer, unit: t3[4].unit }])]) : isTokenPercentage(t3) ? new FunctionNode([c.Function, "calc(", t3[2], t3[3], { value: "calc" }], [c.CloseParen, ")", t3[2], t3[3], void 0], [new TokenNode([c.Ident, "NaN", t3[2], t3[3], { value: "NaN" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Delim, "*", t3[2], t3[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Percentage, "1%", t3[2], t3[3], { value: 1 }])]) : -1 : e3;
}
function patchInfinity(e3) {
  if (-1 === e3) return -1;
  if (isFunctionNode(e3)) return e3;
  const t3 = e3.value;
  if (!isTokenNumeric(t3)) return e3;
  if (Number.isFinite(t3[4].value) || Number.isNaN(t3[4].value)) return e3;
  let r3 = "";
  return Number.NEGATIVE_INFINITY === t3[4].value && (r3 = "-"), isTokenNumber(t3) ? new FunctionNode([c.Function, "calc(", t3[2], t3[3], { value: "calc" }], [c.CloseParen, ")", t3[2], t3[3], void 0], [new TokenNode([c.Ident, r3 + "infinity", t3[2], t3[3], { value: r3 + "infinity" }])]) : isTokenDimension(t3) ? new FunctionNode([c.Function, "calc(", t3[2], t3[3], { value: "calc" }], [c.CloseParen, ")", t3[2], t3[3], void 0], [new TokenNode([c.Ident, r3 + "infinity", t3[2], t3[3], { value: r3 + "infinity" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Delim, "*", t3[2], t3[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Dimension, "1" + t3[4].unit, t3[2], t3[3], { value: 1, type: a.Integer, unit: t3[4].unit }])]) : new FunctionNode([c.Function, "calc(", t3[2], t3[3], { value: "calc" }], [c.CloseParen, ")", t3[2], t3[3], void 0], [new TokenNode([c.Ident, r3 + "infinity", t3[2], t3[3], { value: r3 + "infinity" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Delim, "*", t3[2], t3[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t3[2], t3[3], void 0]]), new TokenNode([c.Percentage, "1%", t3[2], t3[3], { value: 1 }])]);
}
function patchMinusZero(e3) {
  if (-1 === e3) return -1;
  if (isFunctionNode(e3)) return e3;
  const n3 = e3.value;
  return isTokenNumeric(n3) && Object.is(-0, n3[4].value) ? ("-0" === n3[1] || (isTokenPercentage(n3) ? n3[1] = "-0%" : isTokenDimension(n3) ? n3[1] = "-0" + n3[4].unit : n3[1] = "-0"), e3) : e3;
}
function patchPrecision(e3, n3 = 13) {
  if (-1 === e3) return -1;
  if (n3 <= 0) return e3;
  if (isFunctionNode(e3)) return e3;
  const t3 = e3.value;
  if (!isTokenNumeric(t3)) return e3;
  if (Number.isInteger(t3[4].value)) return e3;
  const r3 = Number(t3[4].value.toFixed(n3)).toString();
  return isTokenNumber(t3) ? t3[1] = r3 : isTokenPercentage(t3) ? t3[1] = r3 + "%" : isTokenDimension(t3) && (t3[1] = r3 + t3[4].unit), e3;
}
function patchCanonicalUnit(e3) {
  return -1 === e3 ? -1 : isFunctionNode(e3) ? e3 : isTokenDimension(e3.value) ? (e3.value = toCanonicalUnit(e3.value), e3) : e3;
}
function patchCalcResult(e3, n3) {
  let t3 = e3;
  return n3?.toCanonicalUnits && (t3 = patchCanonicalUnit(t3)), t3 = patchPrecision(t3, n3?.precision), t3 = patchMinusZero(t3), n3?.censorIntoStandardRepresentableValues || (t3 = patchNaN(t3), t3 = patchInfinity(t3)), t3;
}
function tokenizeGlobals(e3) {
  const n3 = /* @__PURE__ */ new Map();
  if (!e3) return n3;
  for (const [t3, r3] of e3) if (isToken(r3)) n3.set(t3, r3);
  else if ("string" == typeof r3) {
    const e4 = tokenizer({ css: r3 }), a3 = e4.nextToken();
    if (e4.nextToken(), !e4.endOfFile()) continue;
    if (!isTokenNumeric(a3)) continue;
    n3.set(t3, a3);
    continue;
  }
  return n3;
}
function calc(e3, n3) {
  return calcFromComponentValues(parseCommaSeparatedListOfComponentValues(tokenize({ css: e3 }), {}), n3).map((e4) => e4.map((e5) => stringify(...e5.tokens())).join("")).join(",");
}
function calcFromComponentValues(e3, n3) {
  const t3 = tokenizeGlobals(n3?.globals);
  return replaceComponentValues2(e3, (e4) => {
    if (!isFunctionNode(e4)) return;
    const r3 = J.get(e4.getName().toLowerCase());
    if (!r3) return;
    const a3 = patchCalcResult(solve(r3(e4, t3, n3 ?? {}), n3 ?? {}), n3);
    return -1 !== a3 ? a3 : void 0;
  });
}
function replaceComponentValues2(n3, r3) {
  for (let a3 = 0; a3 < n3.length; a3++) {
    const o3 = n3[a3];
    walk(o3, (n4, a4) => {
      if ("number" != typeof a4) return;
      const o4 = r3(n4.node);
      if (!o4) return;
      const i3 = [o4], l2 = n4.parent.value[a4 - 1];
      isTokenNode(l2) && isTokenDelim(l2.value) && ("-" === l2.value[4].value || "+" === l2.value[4].value) && i3.splice(0, 0, new WhitespaceNode([[c.Whitespace, " ", ...sourceIndices(n4.node), void 0]]));
      const s3 = n4.parent.value[a4 + 1];
      !s3 || isWhiteSpaceOrCommentNode(s3) || isTokenNode(s3) && (isTokenComma(s3.value) || isTokenColon(s3.value) || isTokenSemicolon(s3.value) || isTokenDelim(s3.value) && "-" !== s3.value[4].value && "+" !== s3.value[4].value) || i3.push(new WhitespaceNode([[c.Whitespace, " ", ...sourceIndices(n4.node), void 0]])), n4.parent.value.splice(a4, 1, ...i3);
    });
  }
  return n3;
}
var Q = new Set(J.keys());

// node_modules/@csstools/css-color-parser/dist/index.mjs
var he, me;
function convertNaNToZero(e3) {
  return [Number.isNaN(e3[0]) ? 0 : e3[0], Number.isNaN(e3[1]) ? 0 : e3[1], Number.isNaN(e3[2]) ? 0 : e3[2]];
}
function colorData_to_XYZ_D50(e3) {
  switch (e3.colorNotation) {
    case he.HEX:
    case he.RGB:
    case he.sRGB:
      return { ...e3, colorNotation: he.XYZ_D50, channels: sRGB_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.Linear_sRGB:
      return { ...e3, colorNotation: he.XYZ_D50, channels: lin_sRGB_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.Display_P3:
      return { ...e3, colorNotation: he.XYZ_D50, channels: P3_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.Linear_Display_P3:
      return { ...e3, colorNotation: he.XYZ_D50, channels: lin_P3_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.Rec2020:
      return { ...e3, colorNotation: he.XYZ_D50, channels: rec_2020_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.A98_RGB:
      return { ...e3, colorNotation: he.XYZ_D50, channels: a98_RGB_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.ProPhoto_RGB:
      return { ...e3, colorNotation: he.XYZ_D50, channels: ProPhoto_RGB_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.HSL:
      return { ...e3, colorNotation: he.XYZ_D50, channels: HSL_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.HWB:
      return { ...e3, colorNotation: he.XYZ_D50, channels: HWB_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.Lab:
      return { ...e3, colorNotation: he.XYZ_D50, channels: Lab_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.OKLab:
      return { ...e3, colorNotation: he.XYZ_D50, channels: OKLab_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.LCH:
      return { ...e3, colorNotation: he.XYZ_D50, channels: LCH_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.OKLCH:
      return { ...e3, colorNotation: he.XYZ_D50, channels: OKLCH_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.XYZ_D50:
      return { ...e3, colorNotation: he.XYZ_D50, channels: XYZ_D50_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    case he.XYZ_D65:
      return { ...e3, colorNotation: he.XYZ_D50, channels: XYZ_D65_to_XYZ_D50(convertNaNToZero(e3.channels)) };
    default:
      throw new Error("Unsupported color notation");
  }
}
!function(e3) {
  e3.A98_RGB = "a98-rgb", e3.Display_P3 = "display-p3", e3.Linear_Display_P3 = "display-p3-linear", e3.HEX = "hex", e3.HSL = "hsl", e3.HWB = "hwb", e3.LCH = "lch", e3.Lab = "lab", e3.Linear_sRGB = "srgb-linear", e3.OKLCH = "oklch", e3.OKLab = "oklab", e3.ProPhoto_RGB = "prophoto-rgb", e3.RGB = "rgb", e3.sRGB = "srgb", e3.Rec2020 = "rec2020", e3.XYZ_D50 = "xyz-d50", e3.XYZ_D65 = "xyz-d65";
}(he || (he = {})), function(e3) {
  e3.ColorKeyword = "color-keyword", e3.HasAlpha = "has-alpha", e3.HasDimensionValues = "has-dimension-values", e3.HasNoneKeywords = "has-none-keywords", e3.HasNumberValues = "has-number-values", e3.HasPercentageAlpha = "has-percentage-alpha", e3.HasPercentageValues = "has-percentage-values", e3.HasVariableAlpha = "has-variable-alpha", e3.Hex = "hex", e3.LegacyHSL = "legacy-hsl", e3.LegacyRGB = "legacy-rgb", e3.NamedColor = "named-color", e3.RelativeColorSyntax = "relative-color-syntax", e3.ColorMix = "color-mix", e3.ColorMixVariadic = "color-mix-variadic", e3.ContrastColor = "contrast-color", e3.RelativeAlphaSyntax = "relative-alpha-syntax", e3.Experimental = "experimental";
}(me || (me = {}));
var pe = /* @__PURE__ */ new Set([he.A98_RGB, he.Display_P3, he.Linear_Display_P3, he.HEX, he.Linear_sRGB, he.ProPhoto_RGB, he.RGB, he.sRGB, he.Rec2020, he.XYZ_D50, he.XYZ_D65]);
function colorDataTo(e3, a3) {
  const n3 = { ...e3 };
  if (e3.colorNotation !== a3) {
    const e4 = colorData_to_XYZ_D50(n3);
    switch (a3) {
      case he.HEX:
      case he.RGB:
        n3.colorNotation = he.RGB, n3.channels = XYZ_D50_to_sRGB(e4.channels);
        break;
      case he.sRGB:
        n3.colorNotation = he.sRGB, n3.channels = XYZ_D50_to_sRGB(e4.channels);
        break;
      case he.Linear_sRGB:
        n3.colorNotation = he.Linear_sRGB, n3.channels = XYZ_D50_to_lin_sRGB(e4.channels);
        break;
      case he.Display_P3:
        n3.colorNotation = he.Display_P3, n3.channels = XYZ_D50_to_P3(e4.channels);
        break;
      case he.Linear_Display_P3:
        n3.colorNotation = he.Linear_Display_P3, n3.channels = XYZ_D50_to_lin_P3(e4.channels);
        break;
      case he.Rec2020:
        n3.colorNotation = he.Rec2020, n3.channels = XYZ_D50_to_rec_2020(e4.channels);
        break;
      case he.ProPhoto_RGB:
        n3.colorNotation = he.ProPhoto_RGB, n3.channels = XYZ_D50_to_ProPhoto(e4.channels);
        break;
      case he.A98_RGB:
        n3.colorNotation = he.A98_RGB, n3.channels = XYZ_D50_to_a98_RGB(e4.channels);
        break;
      case he.HSL:
        n3.colorNotation = he.HSL, n3.channels = XYZ_D50_to_HSL(e4.channels);
        break;
      case he.HWB:
        n3.colorNotation = he.HWB, n3.channels = XYZ_D50_to_HWB(e4.channels);
        break;
      case he.Lab:
        n3.colorNotation = he.Lab, n3.channels = XYZ_D50_to_Lab(e4.channels);
        break;
      case he.LCH:
        n3.colorNotation = he.LCH, n3.channels = XYZ_D50_to_LCH(e4.channels);
        break;
      case he.OKLCH:
        n3.colorNotation = he.OKLCH, n3.channels = XYZ_D50_to_OKLCH(e4.channels);
        break;
      case he.OKLab:
        n3.colorNotation = he.OKLab, n3.channels = XYZ_D50_to_OKLab(e4.channels);
        break;
      case he.XYZ_D50:
        n3.colorNotation = he.XYZ_D50, n3.channels = XYZ_D50_to_XYZ_D50(e4.channels);
        break;
      case he.XYZ_D65:
        n3.colorNotation = he.XYZ_D65, n3.channels = XYZ_D50_to_XYZ_D65(e4.channels);
        break;
      default:
        throw new Error("Unsupported color notation");
    }
  } else n3.channels = convertNaNToZero(e3.channels);
  if (a3 === e3.colorNotation) n3.channels = carryForwardMissingComponents(e3.channels, [0, 1, 2], n3.channels, [0, 1, 2]);
  else if (pe.has(a3) && pe.has(e3.colorNotation)) n3.channels = carryForwardMissingComponents(e3.channels, [0, 1, 2], n3.channels, [0, 1, 2]);
  else switch (a3) {
    case he.HSL:
      switch (e3.colorNotation) {
        case he.HWB:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [0]);
          break;
        case he.Lab:
        case he.OKLab:
          n3.channels = carryForwardMissingComponents(e3.channels, [2], n3.channels, [0]);
          break;
        case he.LCH:
        case he.OKLCH:
          n3.channels = carryForwardMissingComponents(e3.channels, [0, 1, 2], n3.channels, [2, 1, 0]);
      }
      break;
    case he.HWB:
      switch (e3.colorNotation) {
        case he.HSL:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [0]);
          break;
        case he.LCH:
        case he.OKLCH:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [2]);
      }
      break;
    case he.Lab:
    case he.OKLab:
      switch (e3.colorNotation) {
        case he.HSL:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [2]);
          break;
        case he.Lab:
        case he.OKLab:
          n3.channels = carryForwardMissingComponents(e3.channels, [0, 1, 2], n3.channels, [0, 1, 2]);
          break;
        case he.LCH:
        case he.OKLCH:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [0]);
      }
      break;
    case he.LCH:
    case he.OKLCH:
      switch (e3.colorNotation) {
        case he.HSL:
          n3.channels = carryForwardMissingComponents(e3.channels, [0, 1, 2], n3.channels, [2, 1, 0]);
          break;
        case he.HWB:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [2]);
          break;
        case he.Lab:
        case he.OKLab:
          n3.channels = carryForwardMissingComponents(e3.channels, [0], n3.channels, [0]);
          break;
        case he.LCH:
        case he.OKLCH:
          n3.channels = carryForwardMissingComponents(e3.channels, [0, 1, 2], n3.channels, [0, 1, 2]);
      }
  }
  return n3.channels = convertPowerlessComponentsToMissingComponents(n3.channels, a3), n3;
}
function convertPowerlessComponentsToMissingComponents(e3, a3) {
  const n3 = [...e3];
  switch (a3) {
    case he.HSL:
      !Number.isNaN(n3[1]) && reducePrecision(n3[1], 4) <= 0 && (n3[0] = Number.NaN);
      break;
    case he.HWB:
      Math.max(0, reducePrecision(n3[1], 4)) + Math.max(0, reducePrecision(n3[2], 4)) >= 100 && (n3[0] = Number.NaN);
      break;
    case he.LCH:
      !Number.isNaN(n3[1]) && reducePrecision(n3[1], 4) <= 0 && (n3[2] = Number.NaN);
      break;
    case he.OKLCH:
      !Number.isNaN(n3[1]) && reducePrecision(n3[1], 6) <= 0 && (n3[2] = Number.NaN);
  }
  return n3;
}
function convertPowerlessComponentsToZeroValuesForDisplay(e3, a3) {
  const n3 = [...e3];
  switch (a3) {
    case he.HSL:
      (reducePrecision(n3[2]) <= 0 || reducePrecision(n3[2]) >= 100) && (n3[0] = Number.NaN, n3[1] = Number.NaN), reducePrecision(n3[1]) <= 0 && (n3[0] = Number.NaN);
      break;
    case he.HWB:
      Math.max(0, reducePrecision(n3[1])) + Math.max(0, reducePrecision(n3[2])) >= 100 && (n3[0] = Number.NaN);
      break;
    case he.Lab:
      (reducePrecision(n3[0]) <= 0 || reducePrecision(n3[0]) >= 100) && (n3[1] = Number.NaN, n3[2] = Number.NaN);
      break;
    case he.LCH:
      reducePrecision(n3[1]) <= 0 && (n3[2] = Number.NaN), (reducePrecision(n3[0]) <= 0 || reducePrecision(n3[0]) >= 100) && (n3[1] = Number.NaN, n3[2] = Number.NaN);
      break;
    case he.OKLab:
      (reducePrecision(n3[0]) <= 0 || reducePrecision(n3[0]) >= 1) && (n3[1] = Number.NaN, n3[2] = Number.NaN);
      break;
    case he.OKLCH:
      reducePrecision(n3[1]) <= 0 && (n3[2] = Number.NaN), (reducePrecision(n3[0]) <= 0 || reducePrecision(n3[0]) >= 1) && (n3[1] = Number.NaN, n3[2] = Number.NaN);
  }
  return n3;
}
function carryForwardMissingComponents(e3, a3, n3, r3) {
  const o3 = [...n3];
  for (const n4 of a3) Number.isNaN(e3[a3[n4]]) && (o3[r3[n4]] = Number.NaN);
  return o3;
}
function normalizeRelativeColorDataChannels(e3) {
  const a3 = /* @__PURE__ */ new Map();
  switch (e3.colorNotation) {
    case he.RGB:
    case he.HEX:
      a3.set("r", dummyNumberToken(255 * e3.channels[0])), a3.set("g", dummyNumberToken(255 * e3.channels[1])), a3.set("b", dummyNumberToken(255 * e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
      break;
    case he.HSL:
      a3.set("h", dummyNumberToken(e3.channels[0])), a3.set("s", dummyNumberToken(e3.channels[1])), a3.set("l", dummyNumberToken(e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
      break;
    case he.HWB:
      a3.set("h", dummyNumberToken(e3.channels[0])), a3.set("w", dummyNumberToken(e3.channels[1])), a3.set("b", dummyNumberToken(e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
      break;
    case he.Lab:
    case he.OKLab:
      a3.set("l", dummyNumberToken(e3.channels[0])), a3.set("a", dummyNumberToken(e3.channels[1])), a3.set("b", dummyNumberToken(e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
      break;
    case he.LCH:
    case he.OKLCH:
      a3.set("l", dummyNumberToken(e3.channels[0])), a3.set("c", dummyNumberToken(e3.channels[1])), a3.set("h", dummyNumberToken(e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
      break;
    case he.sRGB:
    case he.A98_RGB:
    case he.Display_P3:
    case he.Linear_Display_P3:
    case he.Rec2020:
    case he.Linear_sRGB:
    case he.ProPhoto_RGB:
      a3.set("r", dummyNumberToken(e3.channels[0])), a3.set("g", dummyNumberToken(e3.channels[1])), a3.set("b", dummyNumberToken(e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
      break;
    case he.XYZ_D50:
    case he.XYZ_D65:
      a3.set("x", dummyNumberToken(e3.channels[0])), a3.set("y", dummyNumberToken(e3.channels[1])), a3.set("z", dummyNumberToken(e3.channels[2])), "number" == typeof e3.alpha && a3.set("alpha", dummyNumberToken(e3.alpha));
  }
  return a3;
}
function noneToZeroInRelativeColorDataChannels(e3) {
  const a3 = new Map(e3);
  for (const [n3, r3] of e3) Number.isNaN(r3[4].value) && a3.set(n3, dummyNumberToken(0));
  return a3;
}
function dummyNumberToken(n3) {
  return Number.isNaN(n3) ? [c.Number, "none", -1, -1, { value: Number.NaN, type: a.Number }] : [c.Number, n3.toString(), -1, -1, { value: n3, type: a.Number }];
}
function reducePrecision(e3, a3 = 7) {
  if (Number.isNaN(e3)) return 0;
  const n3 = Math.pow(10, a3);
  return Math.round(e3 * n3) / n3;
}
function colorDataFitsRGB_Gamut(e3) {
  const a3 = { ...e3, channels: [...e3.channels] };
  a3.channels = convertPowerlessComponentsToZeroValuesForDisplay(a3.channels, a3.colorNotation);
  return !colorDataTo(a3, he.RGB).channels.find((e4) => e4 < -1e-5 || e4 > 1.00001);
}
function colorDataFitsDisplayP3_Gamut(e3) {
  const a3 = { ...e3, channels: [...e3.channels] };
  a3.channels = convertPowerlessComponentsToZeroValuesForDisplay(a3.channels, a3.colorNotation);
  return !colorDataTo(a3, he.Display_P3).channels.find((e4) => e4 < -1e-5 || e4 > 1.00001);
}
function normalize(e3, a3, n3, r3) {
  return Math.min(Math.max(e3 / a3, n3), r3);
}
var Ne = /[A-Z]/g;
function toLowerCaseAZ2(e3) {
  return e3.replace(Ne, (e4) => String.fromCharCode(e4.charCodeAt(0) + 32));
}
function normalize_Color_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (isTokenPercentage(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = normalize(t3[4].value, 100, -2147483647, 2147483647);
    return 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = normalize(t3[4].value, 1, -2147483647, 2147483647);
    return 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
var be = /* @__PURE__ */ new Set(["srgb", "srgb-linear", "display-p3", "display-p3-linear", "a98-rgb", "prophoto-rgb", "rec2020", "xyz", "xyz-d50", "xyz-d65"]);
function color$1(e3, a3) {
  const r3 = [], s3 = [], u3 = [], i3 = [];
  let c3, h2, m2 = false, p2 = false;
  const N = { colorNotation: he.sRGB, channels: [0, 0, 0], alpha: 1, syntaxFlags: /* @__PURE__ */ new Set([]) };
  let b2 = r3;
  for (let o3 = 0; o3 < e3.value.length; o3++) {
    let v2 = e3.value[o3];
    if (isWhitespaceNode(v2) || isCommentNode(v2)) for (; isWhitespaceNode(e3.value[o3 + 1]) || isCommentNode(e3.value[o3 + 1]); ) o3++;
    else if (b2 === r3 && r3.length && (b2 = s3), b2 === s3 && s3.length && (b2 = u3), isTokenNode(v2) && isTokenDelim(v2.value) && "/" === v2.value[4].value) {
      if (b2 === i3) return false;
      b2 = i3;
    } else {
      if (isFunctionNode(v2)) {
        if (b2 === i3 && "var" === toLowerCaseAZ2(v2.getName())) {
          N.syntaxFlags.add(me.HasVariableAlpha), b2.push(v2);
          continue;
        }
        if (!Q.has(toLowerCaseAZ2(v2.getName()))) return false;
        const [[e4]] = calcFromComponentValues([[v2]], { censorIntoStandardRepresentableValues: true, globals: h2, precision: -1, toCanonicalUnits: true, rawPercentages: true });
        if (!e4 || !isTokenNode(e4) || !isTokenNumeric(e4.value)) return false;
        Number.isNaN(e4.value[4].value) && (e4.value[4].value = 0), v2 = e4;
      }
      if (b2 === r3 && 0 === r3.length && isTokenNode(v2) && isTokenIdent(v2.value) && be.has(toLowerCaseAZ2(v2.value[4].value))) {
        if (m2) return false;
        m2 = toLowerCaseAZ2(v2.value[4].value), N.colorNotation = colorSpaceNameToColorNotation(m2), p2 && (p2.colorNotation !== N.colorNotation && (p2 = colorDataTo(p2, N.colorNotation)), c3 = normalizeRelativeColorDataChannels(p2), h2 = noneToZeroInRelativeColorDataChannels(c3));
      } else if (b2 === r3 && 0 === r3.length && isTokenNode(v2) && isTokenIdent(v2.value) && "from" === toLowerCaseAZ2(v2.value[4].value)) {
        if (p2) return false;
        if (m2) return false;
        for (; isWhitespaceNode(e3.value[o3 + 1]) || isCommentNode(e3.value[o3 + 1]); ) o3++;
        if (o3++, v2 = e3.value[o3], p2 = a3(v2), false === p2) return false;
        p2.syntaxFlags.has(me.Experimental) && N.syntaxFlags.add(me.Experimental), N.syntaxFlags.add(me.RelativeColorSyntax);
      } else {
        if (!isTokenNode(v2)) return false;
        if (isTokenIdent(v2.value) && c3 && c3.has(toLowerCaseAZ2(v2.value[4].value))) {
          b2.push(new TokenNode(c3.get(toLowerCaseAZ2(v2.value[4].value))));
          continue;
        }
        b2.push(v2);
      }
    }
  }
  if (!m2) return false;
  if (1 !== b2.length) return false;
  if (1 !== r3.length || 1 !== s3.length || 1 !== u3.length) return false;
  if (!isTokenNode(r3[0]) || !isTokenNode(s3[0]) || !isTokenNode(u3[0])) return false;
  if (c3 && !c3.has("alpha")) return false;
  const v = normalize_Color_ChannelValues(r3[0].value, 0, N);
  if (!v || !isTokenNumber(v)) return false;
  const g2 = normalize_Color_ChannelValues(s3[0].value, 1, N);
  if (!g2 || !isTokenNumber(g2)) return false;
  const f3 = normalize_Color_ChannelValues(u3[0].value, 2, N);
  if (!f3 || !isTokenNumber(f3)) return false;
  const d3 = [v, g2, f3];
  if (1 === i3.length) if (N.syntaxFlags.add(me.HasAlpha), isTokenNode(i3[0])) {
    const e4 = normalize_Color_ChannelValues(i3[0].value, 3, N);
    if (!e4 || !isTokenNumber(e4)) return false;
    d3.push(e4);
  } else N.alpha = i3[0];
  else if (c3 && c3.has("alpha")) {
    const e4 = normalize_Color_ChannelValues(c3.get("alpha"), 3, N);
    if (!e4 || !isTokenNumber(e4)) return false;
    d3.push(e4);
  }
  return N.channels = [d3[0][4].value, d3[1][4].value, d3[2][4].value], 4 === d3.length && (N.alpha = d3[3][4].value), N;
}
function colorSpaceNameToColorNotation(e3) {
  switch (e3) {
    case "srgb":
      return he.sRGB;
    case "srgb-linear":
      return he.Linear_sRGB;
    case "display-p3":
      return he.Display_P3;
    case "display-p3-linear":
      return he.Linear_Display_P3;
    case "a98-rgb":
      return he.A98_RGB;
    case "prophoto-rgb":
      return he.ProPhoto_RGB;
    case "rec2020":
      return he.Rec2020;
    case "xyz":
    case "xyz-d65":
      return he.XYZ_D65;
    case "xyz-d50":
      return he.XYZ_D50;
    default:
      throw new Error("Unknown color space name: " + e3);
  }
}
var ve = /* @__PURE__ */ new Set(["srgb", "srgb-linear", "display-p3", "display-p3-linear", "a98-rgb", "prophoto-rgb", "rec2020", "lab", "oklab", "xyz", "xyz-d50", "xyz-d65"]), ge = /* @__PURE__ */ new Set(["hsl", "hwb", "lch", "oklch"]), fe = /* @__PURE__ */ new Set(["shorter", "longer", "increasing", "decreasing"]);
function colorMix(e3, a3) {
  let r3 = null, o3 = null, t3 = null, l2 = false;
  for (let u3 = 0; u3 < e3.value.length; u3++) {
    const i3 = e3.value[u3];
    if (!isWhiteSpaceOrCommentNode(i3)) {
      if (!(r3 || isTokenNode(i3) && isTokenIdent(i3.value) && "in" === toLowerCaseAZ2(i3.value[4].value))) return colorMixRectangular("oklab", colorMixComponents(e3.value, a3));
      if (isTokenNode(i3) && isTokenIdent(i3.value)) {
        if (!r3 && "in" === toLowerCaseAZ2(i3.value[4].value)) {
          r3 = i3;
          continue;
        }
        if (r3 && !o3) {
          o3 = toLowerCaseAZ2(i3.value[4].value);
          continue;
        }
        if (r3 && o3 && !t3 && ge.has(o3)) {
          t3 = toLowerCaseAZ2(i3.value[4].value);
          continue;
        }
        if (r3 && o3 && t3 && !l2 && "hue" === toLowerCaseAZ2(i3.value[4].value)) {
          l2 = true;
          continue;
        }
        return false;
      }
      return !(!isTokenNode(i3) || !isTokenComma(i3.value)) && (!!o3 && (t3 || l2 ? !!(o3 && t3 && l2 && ge.has(o3) && fe.has(t3)) && colorMixPolar(o3, t3, colorMixComponents(e3.value.slice(u3 + 1), a3)) : ve.has(o3) ? colorMixRectangular(o3, colorMixComponents(e3.value.slice(u3 + 1), a3)) : !!ge.has(o3) && colorMixPolar(o3, "shorter", colorMixComponents(e3.value.slice(u3 + 1), a3))));
    }
  }
  return false;
}
function colorMixComponents(e3, a3) {
  const n3 = [];
  let o3 = 1, t3 = false, u3 = false;
  for (let o4 = 0; o4 < e3.length; o4++) {
    let i4 = e3[o4];
    if (!isWhiteSpaceOrCommentNode(i4)) {
      if (!isTokenNode(i4) || !isTokenComma(i4.value)) {
        if (!t3) {
          const e4 = a3(i4);
          if (e4) {
            t3 = e4;
            continue;
          }
        }
        if (!u3) {
          if (isFunctionNode(i4) && Q.has(toLowerCaseAZ2(i4.getName()))) {
            if ([[i4]] = calcFromComponentValues([[i4]], { censorIntoStandardRepresentableValues: true, precision: -1, toCanonicalUnits: true, rawPercentages: true }), !i4 || !isTokenNode(i4) || !isTokenNumeric(i4.value)) return false;
            Number.isNaN(i4.value[4].value) && (i4.value[4].value = 0);
          }
          if (isTokenNode(i4) && isTokenPercentage(i4.value) && i4.value[4].value >= 0) {
            u3 = i4.value[4].value;
            continue;
          }
        }
        return false;
      }
      if (!t3) return false;
      n3.push({ color: t3, percentage: u3 }), t3 = false, u3 = false;
    }
  }
  if (!t3) return false;
  n3.push({ color: t3, percentage: u3 });
  let i3 = 0, c3 = 0;
  for (let e4 = 0; e4 < n3.length; e4++) {
    const a4 = n3[e4].percentage;
    if (false !== a4) {
      if (a4 < 0 || a4 > 100) return false;
      i3 += a4;
    } else c3++;
  }
  const h2 = Math.max(0, 100 - i3);
  i3 = 0;
  for (let e4 = 0; e4 < n3.length; e4++) false === n3[e4].percentage && (n3[e4].percentage = h2 / c3), i3 += n3[e4].percentage;
  if (0 === i3) return { colors: [{ color: { channels: [0, 0, 0], colorNotation: he.sRGB, alpha: 0, syntaxFlags: /* @__PURE__ */ new Set() }, percentage: 0 }], alphaMultiplier: 0 };
  if (i3 > 100) for (let e4 = 0; e4 < n3.length; e4++) {
    let a4 = n3[e4].percentage;
    a4 = a4 / i3 * 100, n3[e4].percentage = a4;
  }
  if (i3 < 100) {
    o3 = i3 / 100;
    for (let e4 = 0; e4 < n3.length; e4++) {
      let a4 = n3[e4].percentage;
      a4 = a4 / i3 * 100, n3[e4].percentage = a4;
    }
  }
  return { colors: n3, alphaMultiplier: o3 };
}
function colorMixRectangular(e3, a3) {
  if (!a3 || !a3.colors.length) return false;
  const n3 = a3.colors.slice();
  n3.reverse();
  let r3 = he.RGB;
  switch (e3) {
    case "srgb":
      r3 = he.RGB;
      break;
    case "srgb-linear":
      r3 = he.Linear_sRGB;
      break;
    case "display-p3":
      r3 = he.Display_P3;
      break;
    case "display-p3-linear":
      r3 = he.Linear_Display_P3;
      break;
    case "a98-rgb":
      r3 = he.A98_RGB;
      break;
    case "prophoto-rgb":
      r3 = he.ProPhoto_RGB;
      break;
    case "rec2020":
      r3 = he.Rec2020;
      break;
    case "lab":
      r3 = he.Lab;
      break;
    case "oklab":
      r3 = he.OKLab;
      break;
    case "xyz-d50":
      r3 = he.XYZ_D50;
      break;
    case "xyz":
    case "xyz-d65":
      r3 = he.XYZ_D65;
      break;
    default:
      return false;
  }
  if (1 === n3.length) {
    const e4 = colorDataTo(n3[0].color, r3);
    return e4.colorNotation = r3, e4.syntaxFlags.add(me.ColorMixVariadic), "number" != typeof e4.alpha ? false : (e4.alpha = e4.alpha * a3.alphaMultiplier, e4);
  }
  for (; n3.length >= 2; ) {
    const e4 = n3.pop(), a4 = n3.pop();
    if (!e4 || !a4) return false;
    const o4 = colorMixRectangularPair(r3, e4.color, e4.percentage, a4.color, a4.percentage);
    if (!o4) return false;
    n3.push({ color: o4, percentage: e4.percentage + a4.percentage });
  }
  const o3 = n3[0]?.color;
  return !!o3 && (a3.colors.some((e4) => e4.color.syntaxFlags.has(me.Experimental)) && o3.syntaxFlags.add(me.Experimental), "number" == typeof o3.alpha && (o3.alpha = o3.alpha * a3.alphaMultiplier, 2 !== a3.colors.length && o3.syntaxFlags.add(me.ColorMixVariadic), o3));
}
function colorMixRectangularPair(e3, a3, n3, r3, o3) {
  const t3 = n3 / (n3 + o3);
  let l2 = a3.alpha;
  if ("number" != typeof l2) return false;
  let s3 = r3.alpha;
  if ("number" != typeof s3) return false;
  l2 = Number.isNaN(l2) ? s3 : l2, s3 = Number.isNaN(s3) ? l2 : s3;
  const u3 = colorDataTo(a3, e3).channels, i3 = colorDataTo(r3, e3).channels;
  u3[0] = fillInMissingComponent(u3[0], i3[0]), i3[0] = fillInMissingComponent(i3[0], u3[0]), u3[1] = fillInMissingComponent(u3[1], i3[1]), i3[1] = fillInMissingComponent(i3[1], u3[1]), u3[2] = fillInMissingComponent(u3[2], i3[2]), i3[2] = fillInMissingComponent(i3[2], u3[2]), u3[0] = premultiply(u3[0], l2), u3[1] = premultiply(u3[1], l2), u3[2] = premultiply(u3[2], l2), i3[0] = premultiply(i3[0], s3), i3[1] = premultiply(i3[1], s3), i3[2] = premultiply(i3[2], s3);
  const c3 = interpolate(l2, s3, t3);
  return { colorNotation: e3, channels: [un_premultiply(interpolate(u3[0], i3[0], t3), c3), un_premultiply(interpolate(u3[1], i3[1], t3), c3), un_premultiply(interpolate(u3[2], i3[2], t3), c3)], alpha: c3, syntaxFlags: /* @__PURE__ */ new Set([me.ColorMix]) };
}
function colorMixPolar(e3, a3, n3) {
  if (!n3 || !n3.colors.length) return false;
  const r3 = n3.colors.slice();
  r3.reverse();
  let o3 = he.HSL;
  switch (e3) {
    case "hsl":
      o3 = he.HSL;
      break;
    case "hwb":
      o3 = he.HWB;
      break;
    case "lch":
      o3 = he.LCH;
      break;
    case "oklch":
      o3 = he.OKLCH;
      break;
    default:
      return false;
  }
  if (1 === r3.length) {
    const e4 = colorDataTo(r3[0].color, o3);
    return e4.colorNotation = o3, e4.syntaxFlags.add(me.ColorMixVariadic), "number" != typeof e4.alpha ? false : (e4.alpha = e4.alpha * n3.alphaMultiplier, e4);
  }
  for (; r3.length >= 2; ) {
    const e4 = r3.pop(), n4 = r3.pop();
    if (!e4 || !n4) return false;
    const t4 = colorMixPolarPair(o3, a3, e4.color, e4.percentage, n4.color, n4.percentage);
    if (!t4) return false;
    r3.push({ color: t4, percentage: e4.percentage + n4.percentage });
  }
  const t3 = r3[0]?.color;
  return !!t3 && (n3.colors.some((e4) => e4.color.syntaxFlags.has(me.Experimental)) && t3.syntaxFlags.add(me.Experimental), "number" == typeof t3.alpha && (t3.alpha = t3.alpha * n3.alphaMultiplier, 2 !== n3.colors.length && t3.syntaxFlags.add(me.ColorMixVariadic), t3));
}
function colorMixPolarPair(e3, a3, n3, r3, o3, t3) {
  const l2 = r3 / (r3 + t3);
  let s3 = 0, u3 = 0, i3 = 0, c3 = 0, h2 = 0, m2 = 0, p2 = n3.alpha;
  if ("number" != typeof p2) return false;
  let N = o3.alpha;
  if ("number" != typeof N) return false;
  p2 = Number.isNaN(p2) ? N : p2, N = Number.isNaN(N) ? p2 : N;
  const b2 = colorDataTo(n3, e3).channels, v = colorDataTo(o3, e3).channels;
  switch (e3) {
    case he.HSL:
    case he.HWB:
      s3 = b2[0], u3 = v[0], i3 = b2[1], c3 = v[1], h2 = b2[2], m2 = v[2];
      break;
    case he.LCH:
    case he.OKLCH:
      i3 = b2[0], c3 = v[0], h2 = b2[1], m2 = v[1], s3 = b2[2], u3 = v[2];
  }
  s3 = fillInMissingComponent(s3, u3), Number.isNaN(s3) && (s3 = 0), u3 = fillInMissingComponent(u3, s3), Number.isNaN(u3) && (u3 = 0), i3 = fillInMissingComponent(i3, c3), c3 = fillInMissingComponent(c3, i3), h2 = fillInMissingComponent(h2, m2), m2 = fillInMissingComponent(m2, h2);
  const g2 = u3 - s3;
  switch (a3) {
    case "shorter":
      g2 > 180 ? s3 += 360 : g2 < -180 && (u3 += 360);
      break;
    case "longer":
      -180 < g2 && g2 < 180 && (g2 > 0 ? s3 += 360 : u3 += 360);
      break;
    case "increasing":
      g2 < 0 && (u3 += 360);
      break;
    case "decreasing":
      g2 > 0 && (s3 += 360);
      break;
    default:
      throw new Error("Unknown hue interpolation method");
  }
  i3 = premultiply(i3, p2), h2 = premultiply(h2, p2), c3 = premultiply(c3, N), m2 = premultiply(m2, N);
  let f3 = [0, 0, 0];
  const d3 = interpolate(p2, N, l2);
  switch (e3) {
    case he.HSL:
    case he.HWB:
      f3 = [interpolate(s3, u3, l2), un_premultiply(interpolate(i3, c3, l2), d3), un_premultiply(interpolate(h2, m2, l2), d3)];
      break;
    case he.LCH:
    case he.OKLCH:
      f3 = [un_premultiply(interpolate(i3, c3, l2), d3), un_premultiply(interpolate(h2, m2, l2), d3), interpolate(s3, u3, l2)];
  }
  return { colorNotation: e3, channels: f3, alpha: d3, syntaxFlags: /* @__PURE__ */ new Set([me.ColorMix]) };
}
function fillInMissingComponent(e3, a3) {
  return Number.isNaN(e3) ? a3 : e3;
}
function interpolate(e3, a3, n3) {
  return e3 * n3 + a3 * (1 - n3);
}
function premultiply(e3, a3) {
  return Number.isNaN(a3) ? e3 : Number.isNaN(e3) ? Number.NaN : e3 * a3;
}
function un_premultiply(e3, a3) {
  return 0 === a3 || Number.isNaN(a3) ? e3 : Number.isNaN(e3) ? Number.NaN : e3 / a3;
}
function hex(e3) {
  const a3 = toLowerCaseAZ2(e3[4].value);
  if (a3.match(/[^a-f0-9]/)) return false;
  const n3 = { colorNotation: he.HEX, channels: [0, 0, 0], alpha: 1, syntaxFlags: /* @__PURE__ */ new Set([me.Hex]) }, r3 = a3.length;
  if (3 === r3) {
    const e4 = a3[0], r4 = a3[1], o3 = a3[2];
    return n3.channels = [parseInt(e4 + e4, 16) / 255, parseInt(r4 + r4, 16) / 255, parseInt(o3 + o3, 16) / 255], n3;
  }
  if (6 === r3) {
    const e4 = a3[0] + a3[1], r4 = a3[2] + a3[3], o3 = a3[4] + a3[5];
    return n3.channels = [parseInt(e4, 16) / 255, parseInt(r4, 16) / 255, parseInt(o3, 16) / 255], n3;
  }
  if (4 === r3) {
    const e4 = a3[0], r4 = a3[1], o3 = a3[2], t3 = a3[3];
    return n3.channels = [parseInt(e4 + e4, 16) / 255, parseInt(r4 + r4, 16) / 255, parseInt(o3 + o3, 16) / 255], n3.alpha = parseInt(t3 + t3, 16) / 255, n3.syntaxFlags.add(me.HasAlpha), n3;
  }
  if (8 === r3) {
    const e4 = a3[0] + a3[1], r4 = a3[2] + a3[3], o3 = a3[4] + a3[5], t3 = a3[6] + a3[7];
    return n3.channels = [parseInt(e4, 16) / 255, parseInt(r4, 16) / 255, parseInt(o3, 16) / 255], n3.alpha = parseInt(t3, 16) / 255, n3.syntaxFlags.add(me.HasAlpha), n3;
  }
  return false;
}
function normalizeHue(n3) {
  if (isTokenNumber(n3)) return n3[4].value = n3[4].value % 360, n3[1] = n3[4].value.toString(), n3;
  if (isTokenDimension(n3)) {
    let r3 = n3[4].value;
    switch (toLowerCaseAZ2(n3[4].unit)) {
      case "deg":
        break;
      case "rad":
        r3 = 180 * n3[4].value / Math.PI;
        break;
      case "grad":
        r3 = 0.9 * n3[4].value;
        break;
      case "turn":
        r3 = 360 * n3[4].value;
        break;
      default:
        return false;
    }
    return r3 %= 360, [c.Number, r3.toString(), n3[2], n3[3], { value: r3, type: a.Number }];
  }
  return false;
}
function normalize_legacy_HSL_ChannelValues(n3, t3, l2) {
  if (0 === t3) {
    const e3 = normalizeHue(n3);
    return false !== e3 && (isTokenDimension(n3) && l2.syntaxFlags.add(me.HasDimensionValues), e3);
  }
  if (isTokenPercentage(n3)) {
    3 === t3 ? l2.syntaxFlags.add(me.HasPercentageAlpha) : l2.syntaxFlags.add(me.HasPercentageValues);
    let r3 = normalize(n3[4].value, 1, 0, 100);
    return 3 === t3 && (r3 = normalize(n3[4].value, 100, 0, 1)), [c.Number, r3.toString(), n3[2], n3[3], { value: r3, type: a.Number }];
  }
  if (isTokenNumber(n3)) {
    if (3 !== t3) return false;
    let r3 = normalize(n3[4].value, 1, 0, 100);
    return 3 === t3 && (r3 = normalize(n3[4].value, 1, 0, 1)), [c.Number, r3.toString(), n3[2], n3[3], { value: r3, type: a.Number }];
  }
  return false;
}
function normalize_modern_HSL_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (0 === l2) {
    const e3 = normalizeHue(t3);
    return false !== e3 && (isTokenDimension(t3) && s3.syntaxFlags.add(me.HasDimensionValues), e3);
  }
  if (isTokenPercentage(t3)) {
    3 === l2 ? s3.syntaxFlags.add(me.HasPercentageAlpha) : s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = t3[4].value;
    return 3 === l2 ? n3 = normalize(t3[4].value, 100, 0, 1) : 1 === l2 && (n3 = normalize(t3[4].value, 1, 0, 2147483647)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = t3[4].value;
    return 3 === l2 ? n3 = normalize(t3[4].value, 1, 0, 1) : 1 === l2 && (n3 = normalize(t3[4].value, 1, 0, 2147483647)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function threeChannelLegacySyntax(e3, a3, n3, r3) {
  const t3 = [], u3 = [], i3 = [], c3 = [], h2 = { colorNotation: n3, channels: [0, 0, 0], alpha: 1, syntaxFlags: new Set(r3) };
  let m2 = t3;
  for (let a4 = 0; a4 < e3.value.length; a4++) {
    let n4 = e3.value[a4];
    if (!isWhitespaceNode(n4) && !isCommentNode(n4)) {
      if (isTokenNode(n4) && isTokenComma(n4.value)) {
        if (m2 === t3) {
          m2 = u3;
          continue;
        }
        if (m2 === u3) {
          m2 = i3;
          continue;
        }
        if (m2 === i3) {
          m2 = c3;
          continue;
        }
        if (m2 === c3) return false;
      }
      if (isFunctionNode(n4)) {
        if (m2 === c3 && "var" === n4.getName().toLowerCase()) {
          h2.syntaxFlags.add(me.HasVariableAlpha), m2.push(n4);
          continue;
        }
        if (!Q.has(n4.getName().toLowerCase())) return false;
        const [[e4]] = calcFromComponentValues([[n4]], { censorIntoStandardRepresentableValues: true, precision: -1, toCanonicalUnits: true, rawPercentages: true });
        if (!e4 || !isTokenNode(e4) || !isTokenNumeric(e4.value)) return false;
        Number.isNaN(e4.value[4].value) && (e4.value[4].value = 0), n4 = e4;
      }
      if (!isTokenNode(n4)) return false;
      m2.push(n4);
    }
  }
  if (1 !== m2.length) return false;
  if (1 !== t3.length || 1 !== u3.length || 1 !== i3.length) return false;
  if (!isTokenNode(t3[0]) || !isTokenNode(u3[0]) || !isTokenNode(i3[0])) return false;
  const p2 = a3(t3[0].value, 0, h2);
  if (!p2 || !isTokenNumber(p2)) return false;
  const N = a3(u3[0].value, 1, h2);
  if (!N || !isTokenNumber(N)) return false;
  const b2 = a3(i3[0].value, 2, h2);
  if (!b2 || !isTokenNumber(b2)) return false;
  const v = [p2, N, b2];
  if (1 === c3.length) if (h2.syntaxFlags.add(me.HasAlpha), isTokenNode(c3[0])) {
    const e4 = a3(c3[0].value, 3, h2);
    if (!e4 || !isTokenNumber(e4)) return false;
    v.push(e4);
  } else h2.alpha = c3[0];
  return h2.channels = [v[0][4].value, v[1][4].value, v[2][4].value], 4 === v.length && (h2.alpha = v[3][4].value), h2;
}
function threeChannelSpaceSeparated(e3, a3, r3, s3, u3) {
  const i3 = [], c3 = [], h2 = [], m2 = [];
  let p2, N, b2 = false;
  const v = { colorNotation: r3, channels: [0, 0, 0], alpha: 1, syntaxFlags: new Set(s3) };
  let g2 = i3;
  for (let a4 = 0; a4 < e3.value.length; a4++) {
    let o3 = e3.value[a4];
    if (isWhitespaceNode(o3) || isCommentNode(o3)) for (; isWhitespaceNode(e3.value[a4 + 1]) || isCommentNode(e3.value[a4 + 1]); ) a4++;
    else if (g2 === i3 && i3.length && (g2 = c3), g2 === c3 && c3.length && (g2 = h2), isTokenNode(o3) && isTokenDelim(o3.value) && "/" === o3.value[4].value) {
      if (g2 === m2) return false;
      g2 = m2;
    } else {
      if (isFunctionNode(o3)) {
        if (g2 === m2 && "var" === o3.getName().toLowerCase()) {
          v.syntaxFlags.add(me.HasVariableAlpha), g2.push(o3);
          continue;
        }
        if (!Q.has(o3.getName().toLowerCase())) return false;
        const [[e4]] = calcFromComponentValues([[o3]], { censorIntoStandardRepresentableValues: true, globals: N, precision: -1, toCanonicalUnits: true, rawPercentages: true });
        if (!e4 || !isTokenNode(e4) || !isTokenNumeric(e4.value)) return false;
        Number.isNaN(e4.value[4].value) && (e4.value[4].value = 0), o3 = e4;
      }
      if (g2 === i3 && 0 === i3.length && isTokenNode(o3) && isTokenIdent(o3.value) && "from" === o3.value[4].value.toLowerCase()) {
        if (b2) return false;
        for (; isWhitespaceNode(e3.value[a4 + 1]) || isCommentNode(e3.value[a4 + 1]); ) a4++;
        if (a4++, o3 = e3.value[a4], b2 = u3(o3), false === b2) return false;
        b2.syntaxFlags.has(me.Experimental) && v.syntaxFlags.add(me.Experimental), v.syntaxFlags.add(me.RelativeColorSyntax), b2.colorNotation !== r3 && (b2 = colorDataTo(b2, r3)), p2 = normalizeRelativeColorDataChannels(b2), N = noneToZeroInRelativeColorDataChannels(p2);
      } else {
        if (!isTokenNode(o3)) return false;
        if (isTokenIdent(o3.value) && p2) {
          const e4 = o3.value[4].value.toLowerCase();
          if (p2.has(e4)) {
            g2.push(new TokenNode(p2.get(e4)));
            continue;
          }
        }
        g2.push(o3);
      }
    }
  }
  if (1 !== g2.length) return false;
  if (1 !== i3.length || 1 !== c3.length || 1 !== h2.length) return false;
  if (!isTokenNode(i3[0]) || !isTokenNode(c3[0]) || !isTokenNode(h2[0])) return false;
  if (p2 && !p2.has("alpha")) return false;
  const f3 = a3(i3[0].value, 0, v);
  if (!f3 || !isTokenNumber(f3)) return false;
  const d3 = a3(c3[0].value, 1, v);
  if (!d3 || !isTokenNumber(d3)) return false;
  const y2 = a3(h2[0].value, 2, v);
  if (!y2 || !isTokenNumber(y2)) return false;
  const _3 = [f3, d3, y2];
  if (1 === m2.length) if (v.syntaxFlags.add(me.HasAlpha), isTokenNode(m2[0])) {
    const e4 = a3(m2[0].value, 3, v);
    if (!e4 || !isTokenNumber(e4)) return false;
    _3.push(e4);
  } else v.alpha = m2[0];
  else if (p2 && p2.has("alpha")) {
    const e4 = a3(p2.get("alpha"), 3, v);
    if (!e4 || !isTokenNumber(e4)) return false;
    _3.push(e4);
  }
  return v.channels = [_3[0][4].value, _3[1][4].value, _3[2][4].value], 4 === _3.length && (v.alpha = _3[3][4].value), v;
}
function hsl(e3, a3) {
  if (e3.value.some((e4) => isTokenNode(e4) && isTokenComma(e4.value))) {
    const a4 = hslCommaSeparated(e3);
    if (false !== a4) return a4;
  }
  {
    const n3 = hslSpaceSeparated(e3, a3);
    if (false !== n3) return n3;
  }
  return false;
}
function hslCommaSeparated(e3) {
  return threeChannelLegacySyntax(e3, normalize_legacy_HSL_ChannelValues, he.HSL, [me.LegacyHSL]);
}
function hslSpaceSeparated(e3, a3) {
  return threeChannelSpaceSeparated(e3, normalize_modern_HSL_ChannelValues, he.HSL, [], a3);
}
function normalize_HWB_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (0 === l2) {
    const e3 = normalizeHue(t3);
    return false !== e3 && (isTokenDimension(t3) && s3.syntaxFlags.add(me.HasDimensionValues), e3);
  }
  if (isTokenPercentage(t3)) {
    3 === l2 ? s3.syntaxFlags.add(me.HasPercentageAlpha) : s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = t3[4].value;
    return 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = t3[4].value;
    return 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function normalize_Lab_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (isTokenPercentage(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = normalize(t3[4].value, 1, 0, 100);
    return 1 === l2 || 2 === l2 ? n3 = normalize(t3[4].value, 0.8, -2147483647, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = normalize(t3[4].value, 1, 0, 100);
    return 1 === l2 || 2 === l2 ? n3 = normalize(t3[4].value, 1, -2147483647, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function lab(e3, a3) {
  return threeChannelSpaceSeparated(e3, normalize_Lab_ChannelValues, he.Lab, [], a3);
}
function normalize_LCH_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (2 === l2) {
    const e3 = normalizeHue(t3);
    return false !== e3 && (isTokenDimension(t3) && s3.syntaxFlags.add(me.HasDimensionValues), e3);
  }
  if (isTokenPercentage(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = normalize(t3[4].value, 1, 0, 100);
    return 1 === l2 ? n3 = normalize(t3[4].value, 100 / 150, 0, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = normalize(t3[4].value, 1, 0, 100);
    return 1 === l2 ? n3 = normalize(t3[4].value, 1, 0, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function lch(e3, a3) {
  return threeChannelSpaceSeparated(e3, normalize_LCH_ChannelValues, he.LCH, [], a3);
}
var de = /* @__PURE__ */ new Map();
for (const [e3, a3] of Object.entries(d2)) de.set(e3, a3);
function namedColor(e3) {
  const a3 = de.get(toLowerCaseAZ2(e3));
  return !!a3 && { colorNotation: he.RGB, channels: [a3[0] / 255, a3[1] / 255, a3[2] / 255], alpha: 1, syntaxFlags: /* @__PURE__ */ new Set([me.ColorKeyword, me.NamedColor]) };
}
function normalize_OKLab_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (isTokenPercentage(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = normalize(t3[4].value, 100, 0, 1);
    return 1 === l2 || 2 === l2 ? n3 = normalize(t3[4].value, 250, -2147483647, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = normalize(t3[4].value, 1, 0, 1);
    return 1 === l2 || 2 === l2 ? n3 = normalize(t3[4].value, 1, -2147483647, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function oklab(e3, a3) {
  return threeChannelSpaceSeparated(e3, normalize_OKLab_ChannelValues, he.OKLab, [], a3);
}
function normalize_OKLCH_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === toLowerCaseAZ2(t3[4].value)) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (2 === l2) {
    const e3 = normalizeHue(t3);
    return false !== e3 && (isTokenDimension(t3) && s3.syntaxFlags.add(me.HasDimensionValues), e3);
  }
  if (isTokenPercentage(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = normalize(t3[4].value, 100, 0, 1);
    return 1 === l2 ? n3 = normalize(t3[4].value, 250, 0, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = normalize(t3[4].value, 1, 0, 1);
    return 1 === l2 ? n3 = normalize(t3[4].value, 1, 0, 2147483647) : 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function oklch(e3, a3) {
  return threeChannelSpaceSeparated(e3, normalize_OKLCH_ChannelValues, he.OKLCH, [], a3);
}
function normalize_legacy_sRGB_ChannelValues(n3, t3, l2) {
  if (isTokenPercentage(n3)) {
    3 === t3 ? l2.syntaxFlags.add(me.HasPercentageAlpha) : l2.syntaxFlags.add(me.HasPercentageValues);
    const r3 = normalize(n3[4].value, 100, 0, 1);
    return [c.Number, r3.toString(), n3[2], n3[3], { value: r3, type: a.Number }];
  }
  if (isTokenNumber(n3)) {
    3 !== t3 && l2.syntaxFlags.add(me.HasNumberValues);
    let r3 = normalize(n3[4].value, 255, 0, 1);
    return 3 === t3 && (r3 = normalize(n3[4].value, 1, 0, 1)), [c.Number, r3.toString(), n3[2], n3[3], { value: r3, type: a.Number }];
  }
  return false;
}
function normalize_modern_sRGB_ChannelValues(t3, l2, s3) {
  if (isTokenIdent(t3) && "none" === t3[4].value.toLowerCase()) return s3.syntaxFlags.add(me.HasNoneKeywords), [c.Number, "none", t3[2], t3[3], { value: Number.NaN, type: a.Number }];
  if (isTokenPercentage(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasPercentageValues);
    let n3 = normalize(t3[4].value, 100, -2147483647, 2147483647);
    return 3 === l2 && (n3 = normalize(t3[4].value, 100, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  if (isTokenNumber(t3)) {
    3 !== l2 && s3.syntaxFlags.add(me.HasNumberValues);
    let n3 = normalize(t3[4].value, 255, -2147483647, 2147483647);
    return 3 === l2 && (n3 = normalize(t3[4].value, 1, 0, 1)), [c.Number, n3.toString(), t3[2], t3[3], { value: n3, type: a.Number }];
  }
  return false;
}
function rgb(e3, a3) {
  if (e3.value.some((e4) => isTokenNode(e4) && isTokenComma(e4.value))) {
    const a4 = rgbCommaSeparated(e3);
    if (false !== a4) return (!a4.syntaxFlags.has(me.HasNumberValues) || !a4.syntaxFlags.has(me.HasPercentageValues)) && a4;
  } else {
    const n3 = rgbSpaceSeparated(e3, a3);
    if (false !== n3) return n3;
  }
  return false;
}
function rgbCommaSeparated(e3) {
  return threeChannelLegacySyntax(e3, normalize_legacy_sRGB_ChannelValues, he.RGB, [me.LegacyRGB]);
}
function rgbSpaceSeparated(e3, a3) {
  return threeChannelSpaceSeparated(e3, normalize_modern_sRGB_ChannelValues, he.RGB, [], a3);
}
function XYZ_D50_to_sRGB_Gamut(e3) {
  const a3 = XYZ_D50_to_sRGB(e3);
  if (inGamut(a3)) return clip(a3);
  let n3 = e3;
  return n3 = XYZ_D50_to_OKLCH(n3), n3[0] < 1e-6 && (n3 = [0, 0, 0]), n3[0] > 0.999999 && (n3 = [1, 0, 0]), gam_sRGB(mapGamutRayTrace(n3, oklch_to_lin_srgb, lin_srgb_to_oklch));
}
function oklch_to_lin_srgb(e3) {
  return e3 = OKLCH_to_OKLab(e3), e3 = OKLab_to_XYZ(e3), XYZ_to_lin_sRGB(e3);
}
function lin_srgb_to_oklch(e3) {
  return e3 = lin_sRGB_to_XYZ(e3), e3 = XYZ_to_OKLab(e3), OKLab_to_OKLCH(e3);
}
function contrastColor(e3, a3) {
  let n3 = false;
  for (let r4 = 0; r4 < e3.value.length; r4++) {
    const o4 = e3.value[r4];
    if (!isWhitespaceNode(o4) && !isCommentNode(o4) && (n3 || (n3 = a3(o4), !n3))) return false;
  }
  if (!n3) return false;
  n3.channels = convertNaNToZero(n3.channels), n3.channels = XYZ_D50_to_sRGB_Gamut(colorData_to_XYZ_D50(n3).channels), n3.colorNotation = he.sRGB;
  const r3 = { colorNotation: he.sRGB, channels: [0, 0, 0], alpha: 1, syntaxFlags: /* @__PURE__ */ new Set([me.ContrastColor, me.Experimental]) }, o3 = contrast_ratio_wcag_2_1(n3.channels, [1, 1, 1]), t3 = contrast_ratio_wcag_2_1(n3.channels, [0, 0, 0]);
  return r3.channels = o3 > t3 ? [1, 1, 1] : [0, 0, 0], r3;
}
function alpha(e3, a3) {
  let r3, s3, u3 = false, i3 = false, c3 = false;
  const h2 = { colorNotation: he.sRGB, channels: [0, 0, 0], alpha: 1, syntaxFlags: /* @__PURE__ */ new Set([]) };
  for (let m2 = 0; m2 < e3.value.length; m2++) {
    let p2 = e3.value[m2];
    if (isWhitespaceNode(p2) || isCommentNode(p2)) for (; isWhitespaceNode(e3.value[m2 + 1]) || isCommentNode(e3.value[m2 + 1]); ) m2++;
    else if (c3 && !u3 && !i3 && isTokenNode(p2) && isTokenDelim(p2.value) && "/" === p2.value[4].value) u3 = true;
    else {
      if (isFunctionNode(p2) && Q.has(toLowerCaseAZ2(p2.getName()))) {
        const [[e4]] = calcFromComponentValues([[p2]], { censorIntoStandardRepresentableValues: true, globals: s3, precision: -1, toCanonicalUnits: true, rawPercentages: true });
        if (!e4 || !isTokenNode(e4) || !isTokenNumeric(e4.value)) return false;
        Number.isNaN(e4.value[4].value) && (e4.value[4].value = 0), p2 = e4;
      }
      if (u3 || i3 || !isTokenNode(p2) || !isTokenIdent(p2.value) || "from" !== toLowerCaseAZ2(p2.value[4].value)) {
        if (!u3) return false;
        if (i3) return false;
        if (isTokenNode(p2)) {
          if (isTokenIdent(p2.value) && "alpha" === toLowerCaseAZ2(p2.value[4].value) && r3 && r3.has("alpha")) {
            h2.alpha = r3.get("alpha")[4].value, i3 = true;
            continue;
          }
          const e4 = normalize_Color_ChannelValues(p2.value, 3, h2);
          if (!e4 || !isTokenNumber(e4)) return false;
          h2.alpha = new TokenNode(e4), i3 = true;
          continue;
        }
        if (isFunctionNode(p2)) {
          const e4 = replaceComponentValues([[p2]], (e5) => {
            if (isTokenNode(e5) && isTokenIdent(e5.value) && "alpha" === toLowerCaseAZ2(e5.value[4].value) && r3 && r3.has("alpha")) return new TokenNode(r3.get("alpha"));
          });
          h2.alpha = e4[0][0], i3 = true;
          continue;
        }
        return false;
      }
      if (c3) return false;
      for (; isWhitespaceNode(e3.value[m2 + 1]) || isCommentNode(e3.value[m2 + 1]); ) m2++;
      if (m2++, p2 = e3.value[m2], c3 = a3(p2), false === c3) return false;
      r3 = normalizeRelativeColorDataChannels(c3), s3 = noneToZeroInRelativeColorDataChannels(r3), h2.syntaxFlags = new Set(c3.syntaxFlags), h2.syntaxFlags.add(me.RelativeAlphaSyntax), h2.channels = [...c3.channels], h2.colorNotation = c3.colorNotation, h2.alpha = c3.alpha;
    }
  }
  return !!r3 && h2;
}
function XYZ_D50_to_P3_Gamut(e3) {
  const a3 = XYZ_D50_to_P3(e3);
  if (inGamut(a3)) return clip(a3);
  let n3 = e3;
  return n3 = XYZ_D50_to_OKLCH(n3), n3[0] < 1e-6 && (n3 = [0, 0, 0]), n3[0] > 0.999999 && (n3 = [1, 0, 0]), gam_P3(mapGamutRayTrace(n3, oklch_to_lin_p3, lin_p3_to_oklch));
}
function oklch_to_lin_p3(e3) {
  return e3 = OKLCH_to_OKLab(e3), e3 = OKLab_to_XYZ(e3), XYZ_to_lin_P3(e3);
}
function lin_p3_to_oklch(e3) {
  return e3 = lin_P3_to_XYZ(e3), e3 = XYZ_to_OKLab(e3), OKLab_to_OKLCH(e3);
}
function toPrecision(e3, a3 = 7) {
  e3 = +e3, a3 = +a3;
  const n3 = (Math.floor(Math.abs(e3)) + "").length;
  if (a3 > n3) return +e3.toFixed(a3 - n3);
  {
    const r3 = 10 ** (n3 - a3);
    return Math.round(e3 / r3) * r3;
  }
}
function serializeWithAlpha(n3, r3, o3, t3) {
  const l2 = [c.CloseParen, ")", -1, -1, void 0];
  if ("number" == typeof n3.alpha) {
    const s3 = Math.min(1, Math.max(0, toPrecision(Number.isNaN(n3.alpha) ? 0 : n3.alpha)));
    return 1 === toPrecision(s3, 4) ? new FunctionNode(r3, l2, t3) : new FunctionNode(r3, l2, [...t3, new WhitespaceNode([o3]), new TokenNode([c.Delim, "/", -1, -1, { value: "/" }]), new WhitespaceNode([o3]), new TokenNode([c.Number, toPrecision(s3, 4).toString(), -1, -1, { value: n3.alpha, type: a.Integer }])]);
  }
  return new FunctionNode(r3, l2, [...t3, new WhitespaceNode([o3]), new TokenNode([c.Delim, "/", -1, -1, { value: "/" }]), new WhitespaceNode([o3]), n3.alpha]);
}
function serializeP3(n3, r3 = true) {
  n3.channels = convertPowerlessComponentsToZeroValuesForDisplay(n3.channels, n3.colorNotation);
  let o3 = n3.channels.map((e3) => Number.isNaN(e3) ? 0 : e3);
  r3 ? o3 = XYZ_D50_to_P3_Gamut(colorData_to_XYZ_D50(n3).channels) : n3.colorNotation !== he.Display_P3 && (o3 = XYZ_D50_to_P3(colorData_to_XYZ_D50(n3).channels));
  const t3 = r3 ? Math.min(1, Math.max(0, toPrecision(o3[0], 6))) : toPrecision(o3[0], 6), l2 = r3 ? Math.min(1, Math.max(0, toPrecision(o3[1], 6))) : toPrecision(o3[1], 6), s3 = r3 ? Math.min(1, Math.max(0, toPrecision(o3[2], 6))) : toPrecision(o3[2], 6), u3 = [c.Function, "color(", -1, -1, { value: "color" }], i3 = [c.Whitespace, " ", -1, -1, void 0];
  return serializeWithAlpha(n3, u3, i3, [new TokenNode([c.Ident, "display-p3", -1, -1, { value: "display-p3" }]), new WhitespaceNode([i3]), new TokenNode([c.Number, t3.toString(), -1, -1, { value: o3[0], type: a.Number }]), new WhitespaceNode([i3]), new TokenNode([c.Number, l2.toString(), -1, -1, { value: o3[1], type: a.Number }]), new WhitespaceNode([i3]), new TokenNode([c.Number, s3.toString(), -1, -1, { value: o3[2], type: a.Number }])]);
}
function serializeRGB(n3, r3 = true) {
  n3.channels = convertPowerlessComponentsToZeroValuesForDisplay(n3.channels, n3.colorNotation);
  let o3 = n3.channels.map((e3) => Number.isNaN(e3) ? 0 : e3);
  o3 = r3 ? XYZ_D50_to_sRGB_Gamut(colorData_to_XYZ_D50(n3).channels) : XYZ_D50_to_sRGB(colorData_to_XYZ_D50(n3).channels);
  const t3 = Math.min(255, Math.max(0, Math.round(255 * toPrecision(o3[0])))), l2 = Math.min(255, Math.max(0, Math.round(255 * toPrecision(o3[1])))), s3 = Math.min(255, Math.max(0, Math.round(255 * toPrecision(o3[2])))), u3 = [c.CloseParen, ")", -1, -1, void 0], i3 = [c.Whitespace, " ", -1, -1, void 0], c3 = [c.Comma, ",", -1, -1, void 0], h2 = [new TokenNode([c.Number, t3.toString(), -1, -1, { value: Math.min(255, 255 * Math.max(0, o3[0])), type: a.Integer }]), new TokenNode(c3), new WhitespaceNode([i3]), new TokenNode([c.Number, l2.toString(), -1, -1, { value: Math.min(255, 255 * Math.max(0, o3[1])), type: a.Integer }]), new TokenNode(c3), new WhitespaceNode([i3]), new TokenNode([c.Number, s3.toString(), -1, -1, { value: Math.min(255, 255 * Math.max(0, o3[2])), type: a.Integer }])];
  if ("number" == typeof n3.alpha) {
    const r4 = Math.min(1, Math.max(0, toPrecision(Number.isNaN(n3.alpha) ? 0 : n3.alpha)));
    return 1 === toPrecision(r4, 4) ? new FunctionNode([c.Function, "rgb(", -1, -1, { value: "rgb" }], u3, h2) : new FunctionNode([c.Function, "rgba(", -1, -1, { value: "rgba" }], u3, [...h2, new TokenNode(c3), new WhitespaceNode([i3]), new TokenNode([c.Number, toPrecision(r4, 4).toString(), -1, -1, { value: n3.alpha, type: a.Number }])]);
  }
  return new FunctionNode([c.Function, "rgba(", -1, -1, { value: "rgba" }], u3, [...h2, new TokenNode(c3), new WhitespaceNode([i3]), n3.alpha]);
}
function serializeHSL(n3, r3 = true) {
  n3.channels = convertPowerlessComponentsToZeroValuesForDisplay(n3.channels, n3.colorNotation);
  let o3 = n3.channels.map((e3) => Number.isNaN(e3) ? 0 : e3);
  o3 = XYZ_D50_to_HSL(r3 ? sRGB_to_XYZ_D50(XYZ_D50_to_sRGB_Gamut(colorData_to_XYZ_D50(n3).channels)) : colorData_to_XYZ_D50(n3).channels), o3 = o3.map((e3) => Number.isNaN(e3) ? 0 : e3);
  const t3 = Math.min(360, Math.max(0, Math.round(toPrecision(o3[0])))), l2 = Math.min(100, Math.max(0, Math.round(toPrecision(o3[1])))), s3 = Math.min(100, Math.max(0, Math.round(toPrecision(o3[2])))), u3 = [c.CloseParen, ")", -1, -1, void 0], i3 = [c.Whitespace, " ", -1, -1, void 0], c3 = [c.Comma, ",", -1, -1, void 0], h2 = [new TokenNode([c.Number, t3.toString(), -1, -1, { value: o3[0], type: a.Integer }]), new TokenNode(c3), new WhitespaceNode([i3]), new TokenNode([c.Percentage, l2.toString() + "%", -1, -1, { value: o3[1] }]), new TokenNode(c3), new WhitespaceNode([i3]), new TokenNode([c.Percentage, s3.toString() + "%", -1, -1, { value: o3[2] }])];
  if ("number" == typeof n3.alpha) {
    const r4 = Math.min(1, Math.max(0, toPrecision(Number.isNaN(n3.alpha) ? 0 : n3.alpha)));
    return 1 === toPrecision(r4, 4) ? new FunctionNode([c.Function, "hsl(", -1, -1, { value: "hsl" }], u3, h2) : new FunctionNode([c.Function, "hsla(", -1, -1, { value: "hsla" }], u3, [...h2, new TokenNode(c3), new WhitespaceNode([i3]), new TokenNode([c.Number, toPrecision(r4, 4).toString(), -1, -1, { value: n3.alpha, type: a.Number }])]);
  }
  return new FunctionNode([c.Function, "hsla(", -1, -1, { value: "hsla" }], u3, [...h2, new TokenNode(c3), new WhitespaceNode([i3]), n3.alpha]);
}
function serializeOKLCH(n3) {
  n3.channels = convertPowerlessComponentsToZeroValuesForDisplay(n3.channels, n3.colorNotation);
  let r3 = n3.channels.map((e3) => Number.isNaN(e3) ? 0 : e3);
  n3.colorNotation !== he.OKLCH && (r3 = XYZ_D50_to_OKLCH(colorData_to_XYZ_D50(n3).channels));
  const o3 = toPrecision(r3[0], 6), t3 = toPrecision(r3[1], 6), l2 = toPrecision(r3[2], 6), s3 = [c.Function, "oklch(", -1, -1, { value: "oklch" }], u3 = [c.Whitespace, " ", -1, -1, void 0];
  return serializeWithAlpha(n3, s3, u3, [new TokenNode([c.Number, o3.toString(), -1, -1, { value: r3[0], type: a.Number }]), new WhitespaceNode([u3]), new TokenNode([c.Number, t3.toString(), -1, -1, { value: r3[1], type: a.Number }]), new WhitespaceNode([u3]), new TokenNode([c.Number, l2.toString(), -1, -1, { value: r3[2], type: a.Number }])]);
}
function color(e3) {
  if (isFunctionNode(e3)) {
    switch (toLowerCaseAZ2(e3.getName())) {
      case "rgb":
      case "rgba":
        return rgb(e3, color);
      case "hsl":
      case "hsla":
        return hsl(e3, color);
      case "hwb":
        return a3 = color, threeChannelSpaceSeparated(e3, normalize_HWB_ChannelValues, he.HWB, [], a3);
      case "lab":
        return lab(e3, color);
      case "lch":
        return lch(e3, color);
      case "oklab":
        return oklab(e3, color);
      case "oklch":
        return oklch(e3, color);
      case "color":
        return color$1(e3, color);
      case "color-mix":
        return colorMix(e3, color);
      case "contrast-color":
        return contrastColor(e3, color);
      case "alpha":
        return alpha(e3, color);
    }
  }
  var a3;
  if (isTokenNode(e3)) {
    if (isTokenHash(e3.value)) return hex(e3.value);
    if (isTokenIdent(e3.value)) {
      const a4 = namedColor(e3.value[4].value);
      return false !== a4 ? a4 : "transparent" === toLowerCaseAZ2(e3.value[4].value) && { colorNotation: he.RGB, channels: [0, 0, 0], alpha: 0, syntaxFlags: /* @__PURE__ */ new Set([me.ColorKeyword]) };
    }
  }
  return false;
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  ColorNotation,
  SyntaxFlag,
  color,
  colorDataFitsDisplayP3_Gamut,
  colorDataFitsRGB_Gamut,
  serializeHSL,
  serializeOKLCH,
  serializeP3,
  serializeRGB
});
/*! Bundled license information:

@csstools/color-helpers/dist/index.mjs:
  (**
   * Bradford chromatic adaptation from D50 to D65
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Bradford chromatic adaptation from D65 to D50
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see http://www.brucelindbloom.com/index.html?Eqn_ChromAdapt.html
   *)
  (**
   * @param {number} hue - Hue as degrees 0..360
   * @param {number} sat - Saturation as percentage 0..100
   * @param {number} light - Lightness as percentage 0..100
   * @return {number[]} Array of sRGB components; in-gamut colors in range [0..1]
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/hslToRgb.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/hslToRgb.js
   *)
  (**
   * @param {number} hue -  Hue as degrees 0..360
   * @param {number} white -  Whiteness as percentage 0..100
   * @param {number} black -  Blackness as percentage 0..100
   * @return {number[]} Array of RGB components 0..1
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/hwbToRgb.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/hwbToRgb.js
   *)
  (**
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert Lab to D50-adapted XYZ
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
   *)
  (**
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js
   *)
  (**
   * Given OKLab, convert to XYZ relative to D65
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js
   *)
  (**
   * Assuming XYZ is relative to D50, convert to CIE Lab
   * from CIE standard, which now defines these as a rational fraction
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *
   * XYZ <-> LMS matrices recalculated for consistent reference white
   * @see https://github.com/w3c/csswg-drafts/issues/6642#issuecomment-943521484
   *)
  (**
   * Convert XYZ to linear-light rec2020
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert XYZ to linear-light P3
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert D50 XYZ to linear-light prophoto-rgb
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
   *)
  (**
   * Convert XYZ to linear-light a98-rgb
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light rec2020 RGB  in the range 0.0-1.0
   * to gamma corrected form ITU-R BT.2020-2 p.4
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light sRGB values in the range 0.0-1.0 to gamma corrected form
   * Extended transfer function:
   *  For negative values, linear portion extends on reflection
   *  of axis, then uses reflected pow below that
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://en.wikipedia.org/wiki/SRGB
   *)
  (**
   * Convert an array of linear-light display-p3 RGB in the range 0.0-1.0
   * to gamma corrected form
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light prophoto-rgb in the range 0.0-1.0
   * to gamma corrected form.
   * Transfer curve is gamma 1.8 with a small linear portion.
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light a98-rgb in the range 0.0-1.0
   * to gamma corrected form. Negative values are also now accepted
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of rec2020 RGB values in the range 0.0 - 1.0
   * to linear light (un-companded) form.
   * ITU-R BT.2020-2 p.4
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light rec2020 values to CIE XYZ
   * using  D65 (no chromatic adaptation)
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
   *)
  (**
   * Convert an array of of sRGB values where in-gamut values are in the range
   * [0 - 1] to linear light (un-companded) form.
   * Extended transfer function:
   *  For negative values, linear portion is extended on reflection of axis,
   *  then reflected power function is used.
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://en.wikipedia.org/wiki/SRGB
   *)
  (**
   * Convert an array of display-p3 RGB values in the range 0.0 - 1.0
   * to linear light (un-companded) form.
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light display-p3 values to CIE XYZ
   * using D65 (no chromatic adaptation)
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
   *)
  (**
   * Convert an array of prophoto-rgb values where in-gamut Colors are in the
   * range [0.0 - 1.0] to linear light (un-companded) form. Transfer curve is
   * gamma 1.8 with a small linear portion. Extended transfer function
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of linear-light prophoto-rgb values to CIE D50 XYZ.
   * Matrix cannot be expressed in rational form, but is calculated to 64 bit accuracy.
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see see https://github.com/w3c/csswg-drafts/issues/7675
   *)
  (**
   * Convert an array of linear-light a98-rgb values to CIE XYZ
   * http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
   * has greater numerical precision than section 4.3.5.3 of
   * https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf
   * but the values below were calculated from first principles
   * from the chromaticity coordinates of R G B W
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see http://www.brucelindbloom.com/index.html?Eqn_RGB_XYZ_Matrix.html
   * @see https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/matrixmaker.html
   *)
  (**
   * Convert an array of linear-light sRGB values to CIE XYZ
   * using sRGB's own white, D65 (no chromatic adaptation)
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * Convert an array of gamma-corrected sRGB values in the 0.0 to 1.0 range to HSL.
   *
   * @param {Color} RGB [r, g, b]
   * - Red component 0..1
   * - Green component 0..1
   * - Blue component 0..1
   * @return {number[]} Array of HSL values: Hue as degrees 0..360, Saturation and Lightness as percentages 0..100
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/utilities.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/better-rgbToHsl.js
   *)
  (**
   * Convert an array of a98-rgb values in the range 0.0 - 1.0
   * to linear light (un-companded) form. Negative values are also now accepted
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
  (**
   * @description Calculate deltaE OK which is the simple root sum of squares
   * @param {number[]} reference - Array of OKLab values: L as 0..1, a and b as -1..1
   * @param {number[]} sample - Array of OKLab values: L as 0..1, a and b as -1..1
   * @return {number} How different a color sample is from reference
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/deltaEOK.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   * @see https://github.com/w3c/csswg-drafts/blob/main/css-color-4/deltaEOK.js
   *)
  (**
   * @license MIT https://github.com/facelessuser/coloraide/blob/main/LICENSE.md
   *)
*/
