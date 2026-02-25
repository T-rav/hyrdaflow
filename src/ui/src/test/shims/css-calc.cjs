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

// node_modules/@csstools/css-calc/dist/index.mjs
var dist_exports = {};
__export(dist_exports, {
  ParseError: () => ParseError2,
  ParseErrorMessage: () => y,
  ParseErrorWithComponentValues: () => ParseErrorWithComponentValues,
  calc: () => calc,
  calcFromComponentValues: () => calcFromComponentValues,
  mathFunctionNames: () => Q
});
module.exports = __toCommonJS(dist_exports);

// node_modules/@csstools/css-tokenizer/dist/index.mjs
var ParseError = class extends Error {
  sourceStart;
  sourceEnd;
  parserState;
  constructor(e2, n2, t2, o2) {
    super(e2), this.name = "ParseError", this.sourceStart = n2, this.sourceEnd = t2, this.parserState = o2;
  }
};
var ParseErrorWithToken = class extends ParseError {
  token;
  constructor(e2, n2, t2, o2, r2) {
    super(e2, n2, t2, o2), this.token = r2;
  }
};
var e = { UnexpectedNewLineInString: "Unexpected newline while consuming a string token.", UnexpectedEOFInString: "Unexpected EOF while consuming a string token.", UnexpectedEOFInComment: "Unexpected EOF while consuming a comment.", UnexpectedEOFInURL: "Unexpected EOF while consuming a url token.", UnexpectedEOFInEscapedCodePoint: "Unexpected EOF while consuming an escaped code point.", UnexpectedCharacterInURL: "Unexpected character while consuming a url token.", InvalidEscapeSequenceInURL: "Invalid escape sequence while consuming a url token.", InvalidEscapeSequenceAfterBackslash: 'Invalid escape sequence after "\\"' }, n = "undefined" != typeof globalThis && "structuredClone" in globalThis;
function cloneTokens(e2) {
  return n ? structuredClone(e2) : JSON.parse(JSON.stringify(e2));
}
function stringify(...e2) {
  let n2 = "";
  for (let t2 = 0; t2 < e2.length; t2++) n2 += e2[t2][1];
  return n2;
}
var t = 13, o = 45, r = 10, i = 43, s = 65533;
function checkIfFourCodePointsWouldStartCDO(e2) {
  return 60 === e2.source.codePointAt(e2.cursor) && 33 === e2.source.codePointAt(e2.cursor + 1) && e2.source.codePointAt(e2.cursor + 2) === o && e2.source.codePointAt(e2.cursor + 3) === o;
}
function isDigitCodePoint(e2) {
  return e2 >= 48 && e2 <= 57;
}
function isUppercaseLetterCodePoint(e2) {
  return e2 >= 65 && e2 <= 90;
}
function isLowercaseLetterCodePoint(e2) {
  return e2 >= 97 && e2 <= 122;
}
function isHexDigitCodePoint(e2) {
  return e2 >= 48 && e2 <= 57 || e2 >= 97 && e2 <= 102 || e2 >= 65 && e2 <= 70;
}
function isLetterCodePoint(e2) {
  return isLowercaseLetterCodePoint(e2) || isUppercaseLetterCodePoint(e2);
}
function isIdentStartCodePoint(e2) {
  return isLetterCodePoint(e2) || isNonASCII_IdentCodePoint(e2) || 95 === e2;
}
function isIdentCodePoint(e2) {
  return isIdentStartCodePoint(e2) || isDigitCodePoint(e2) || e2 === o;
}
function isNonASCII_IdentCodePoint(e2) {
  return 183 === e2 || 8204 === e2 || 8205 === e2 || 8255 === e2 || 8256 === e2 || 8204 === e2 || (192 <= e2 && e2 <= 214 || 216 <= e2 && e2 <= 246 || 248 <= e2 && e2 <= 893 || 895 <= e2 && e2 <= 8191 || 8304 <= e2 && e2 <= 8591 || 11264 <= e2 && e2 <= 12271 || 12289 <= e2 && e2 <= 55295 || 63744 <= e2 && e2 <= 64975 || 65008 <= e2 && e2 <= 65533 || (0 === e2 || (!!isSurrogate(e2) || e2 >= 65536)));
}
function isNonPrintableCodePoint(e2) {
  return 11 === e2 || 127 === e2 || 0 <= e2 && e2 <= 8 || 14 <= e2 && e2 <= 31;
}
function isNewLine(e2) {
  return e2 === r || e2 === t || 12 === e2;
}
function isWhitespace(e2) {
  return 32 === e2 || e2 === r || 9 === e2 || e2 === t || 12 === e2;
}
function isSurrogate(e2) {
  return e2 >= 55296 && e2 <= 57343;
}
function checkIfTwoCodePointsAreAValidEscape(e2) {
  return 92 === e2.source.codePointAt(e2.cursor) && !isNewLine(e2.source.codePointAt(e2.cursor + 1) ?? -1);
}
function checkIfThreeCodePointsWouldStartAnIdentSequence(e2, n2) {
  return n2.source.codePointAt(n2.cursor) === o ? n2.source.codePointAt(n2.cursor + 1) === o || (!!isIdentStartCodePoint(n2.source.codePointAt(n2.cursor + 1) ?? -1) || 92 === n2.source.codePointAt(n2.cursor + 1) && !isNewLine(n2.source.codePointAt(n2.cursor + 2) ?? -1)) : !!isIdentStartCodePoint(n2.source.codePointAt(n2.cursor) ?? -1) || checkIfTwoCodePointsAreAValidEscape(n2);
}
function checkIfThreeCodePointsWouldStartANumber(e2) {
  return e2.source.codePointAt(e2.cursor) === i || e2.source.codePointAt(e2.cursor) === o ? !!isDigitCodePoint(e2.source.codePointAt(e2.cursor + 1) ?? -1) || 46 === e2.source.codePointAt(e2.cursor + 1) && isDigitCodePoint(e2.source.codePointAt(e2.cursor + 2) ?? -1) : 46 === e2.source.codePointAt(e2.cursor) ? isDigitCodePoint(e2.source.codePointAt(e2.cursor + 1) ?? -1) : isDigitCodePoint(e2.source.codePointAt(e2.cursor) ?? -1);
}
function checkIfTwoCodePointsStartAComment(e2) {
  return 47 === e2.source.codePointAt(e2.cursor) && 42 === e2.source.codePointAt(e2.cursor + 1);
}
function checkIfThreeCodePointsWouldStartCDC(e2) {
  return e2.source.codePointAt(e2.cursor) === o && e2.source.codePointAt(e2.cursor + 1) === o && 62 === e2.source.codePointAt(e2.cursor + 2);
}
var c, a, u;
function mirrorVariantType(e2) {
  switch (e2) {
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
function mirrorVariant(e2) {
  switch (e2[0]) {
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
function consumeComment(n2, t2) {
  for (t2.advanceCodePoint(2); ; ) {
    const o2 = t2.readCodePoint();
    if (void 0 === o2) {
      const o3 = [c.Comment, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, void 0];
      return n2.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInComment, t2.representationStart, t2.representationEnd, ["4.3.2. Consume comments", "Unexpected EOF"], o3)), o3;
    }
    if (42 === o2 && (void 0 !== t2.source.codePointAt(t2.cursor) && 47 === t2.source.codePointAt(t2.cursor))) {
      t2.advanceCodePoint();
      break;
    }
  }
  return [c.Comment, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, void 0];
}
function consumeEscapedCodePoint(n2, o2) {
  const i2 = o2.readCodePoint();
  if (void 0 === i2) return n2.onParseError(new ParseError(e.UnexpectedEOFInEscapedCodePoint, o2.representationStart, o2.representationEnd, ["4.3.7. Consume an escaped code point", "Unexpected EOF"])), s;
  if (isHexDigitCodePoint(i2)) {
    const e2 = [i2];
    let n3;
    for (; void 0 !== (n3 = o2.source.codePointAt(o2.cursor)) && isHexDigitCodePoint(n3) && e2.length < 6; ) e2.push(n3), o2.advanceCodePoint();
    isWhitespace(o2.source.codePointAt(o2.cursor) ?? -1) && (o2.source.codePointAt(o2.cursor) === t && o2.source.codePointAt(o2.cursor + 1) === r && o2.advanceCodePoint(), o2.advanceCodePoint());
    const c2 = parseInt(String.fromCodePoint(...e2), 16);
    return 0 === c2 || isSurrogate(c2) || c2 > 1114111 ? s : c2;
  }
  return 0 === i2 || isSurrogate(i2) ? s : i2;
}
function consumeIdentSequence(e2, n2) {
  const t2 = [];
  for (; ; ) {
    const o2 = n2.source.codePointAt(n2.cursor) ?? -1;
    if (0 === o2 || isSurrogate(o2)) t2.push(s), n2.advanceCodePoint(+(o2 > 65535) + 1);
    else if (isIdentCodePoint(o2)) t2.push(o2), n2.advanceCodePoint(+(o2 > 65535) + 1);
    else {
      if (!checkIfTwoCodePointsAreAValidEscape(n2)) return t2;
      n2.advanceCodePoint(), t2.push(consumeEscapedCodePoint(e2, n2));
    }
  }
}
function consumeHashToken(e2, n2) {
  n2.advanceCodePoint();
  const t2 = n2.source.codePointAt(n2.cursor);
  if (void 0 !== t2 && (isIdentCodePoint(t2) || checkIfTwoCodePointsAreAValidEscape(n2))) {
    let t3 = u.Unrestricted;
    checkIfThreeCodePointsWouldStartAnIdentSequence(0, n2) && (t3 = u.ID);
    const o2 = consumeIdentSequence(e2, n2);
    return [c.Hash, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: String.fromCodePoint(...o2), type: t3 }];
  }
  return [c.Delim, "#", n2.representationStart, n2.representationEnd, { value: "#" }];
}
function consumeNumber(e2, n2) {
  let t2 = a.Integer;
  for (n2.source.codePointAt(n2.cursor) !== i && n2.source.codePointAt(n2.cursor) !== o || n2.advanceCodePoint(); isDigitCodePoint(n2.source.codePointAt(n2.cursor) ?? -1); ) n2.advanceCodePoint();
  if (46 === n2.source.codePointAt(n2.cursor) && isDigitCodePoint(n2.source.codePointAt(n2.cursor + 1) ?? -1)) for (n2.advanceCodePoint(2), t2 = a.Number; isDigitCodePoint(n2.source.codePointAt(n2.cursor) ?? -1); ) n2.advanceCodePoint();
  if (101 === n2.source.codePointAt(n2.cursor) || 69 === n2.source.codePointAt(n2.cursor)) {
    if (isDigitCodePoint(n2.source.codePointAt(n2.cursor + 1) ?? -1)) n2.advanceCodePoint(2);
    else {
      if (n2.source.codePointAt(n2.cursor + 1) !== o && n2.source.codePointAt(n2.cursor + 1) !== i || !isDigitCodePoint(n2.source.codePointAt(n2.cursor + 2) ?? -1)) return t2;
      n2.advanceCodePoint(3);
    }
    for (t2 = a.Number; isDigitCodePoint(n2.source.codePointAt(n2.cursor) ?? -1); ) n2.advanceCodePoint();
  }
  return t2;
}
function consumeNumericToken(e2, n2) {
  let t2;
  {
    const e3 = n2.source.codePointAt(n2.cursor);
    e3 === o ? t2 = "-" : e3 === i && (t2 = "+");
  }
  const r2 = consumeNumber(0, n2), s2 = parseFloat(n2.source.slice(n2.representationStart, n2.representationEnd + 1));
  if (checkIfThreeCodePointsWouldStartAnIdentSequence(0, n2)) {
    const o2 = consumeIdentSequence(e2, n2);
    return [c.Dimension, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: s2, signCharacter: t2, type: r2, unit: String.fromCodePoint(...o2) }];
  }
  return 37 === n2.source.codePointAt(n2.cursor) ? (n2.advanceCodePoint(), [c.Percentage, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: s2, signCharacter: t2 }]) : [c.Number, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: s2, signCharacter: t2, type: r2 }];
}
function consumeWhiteSpace(e2) {
  for (; isWhitespace(e2.source.codePointAt(e2.cursor) ?? -1); ) e2.advanceCodePoint();
  return [c.Whitespace, e2.source.slice(e2.representationStart, e2.representationEnd + 1), e2.representationStart, e2.representationEnd, void 0];
}
!function(e2) {
  e2.Comment = "comment", e2.AtKeyword = "at-keyword-token", e2.BadString = "bad-string-token", e2.BadURL = "bad-url-token", e2.CDC = "CDC-token", e2.CDO = "CDO-token", e2.Colon = "colon-token", e2.Comma = "comma-token", e2.Delim = "delim-token", e2.Dimension = "dimension-token", e2.EOF = "EOF-token", e2.Function = "function-token", e2.Hash = "hash-token", e2.Ident = "ident-token", e2.Number = "number-token", e2.Percentage = "percentage-token", e2.Semicolon = "semicolon-token", e2.String = "string-token", e2.URL = "url-token", e2.Whitespace = "whitespace-token", e2.OpenParen = "(-token", e2.CloseParen = ")-token", e2.OpenSquare = "[-token", e2.CloseSquare = "]-token", e2.OpenCurly = "{-token", e2.CloseCurly = "}-token", e2.UnicodeRange = "unicode-range-token";
}(c || (c = {})), function(e2) {
  e2.Integer = "integer", e2.Number = "number";
}(a || (a = {})), function(e2) {
  e2.Unrestricted = "unrestricted", e2.ID = "id";
}(u || (u = {}));
var Reader = class {
  cursor = 0;
  source = "";
  representationStart = 0;
  representationEnd = -1;
  constructor(e2) {
    this.source = e2;
  }
  advanceCodePoint(e2 = 1) {
    this.cursor = this.cursor + e2, this.representationEnd = this.cursor - 1;
  }
  readCodePoint() {
    const e2 = this.source.codePointAt(this.cursor);
    if (void 0 !== e2) return this.cursor = this.cursor + 1, this.representationEnd = this.cursor - 1, e2;
  }
  unreadCodePoint(e2 = 1) {
    this.cursor = this.cursor - e2, this.representationEnd = this.cursor - 1;
  }
  resetRepresentation() {
    this.representationStart = this.cursor, this.representationEnd = -1;
  }
};
function consumeStringToken(n2, o2) {
  let i2 = "";
  const a2 = o2.readCodePoint();
  for (; ; ) {
    const u2 = o2.readCodePoint();
    if (void 0 === u2) {
      const t2 = [c.String, o2.source.slice(o2.representationStart, o2.representationEnd + 1), o2.representationStart, o2.representationEnd, { value: i2 }];
      return n2.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInString, o2.representationStart, o2.representationEnd, ["4.3.5. Consume a string token", "Unexpected EOF"], t2)), t2;
    }
    if (isNewLine(u2)) {
      o2.unreadCodePoint();
      const i3 = [c.BadString, o2.source.slice(o2.representationStart, o2.representationEnd + 1), o2.representationStart, o2.representationEnd, void 0];
      return n2.onParseError(new ParseErrorWithToken(e.UnexpectedNewLineInString, o2.representationStart, o2.source.codePointAt(o2.cursor) === t && o2.source.codePointAt(o2.cursor + 1) === r ? o2.representationEnd + 2 : o2.representationEnd + 1, ["4.3.5. Consume a string token", "Unexpected newline"], i3)), i3;
    }
    if (u2 === a2) return [c.String, o2.source.slice(o2.representationStart, o2.representationEnd + 1), o2.representationStart, o2.representationEnd, { value: i2 }];
    if (92 !== u2) 0 === u2 || isSurrogate(u2) ? i2 += String.fromCodePoint(s) : i2 += String.fromCodePoint(u2);
    else {
      if (void 0 === o2.source.codePointAt(o2.cursor)) continue;
      if (isNewLine(o2.source.codePointAt(o2.cursor) ?? -1)) {
        o2.source.codePointAt(o2.cursor) === t && o2.source.codePointAt(o2.cursor + 1) === r && o2.advanceCodePoint(), o2.advanceCodePoint();
        continue;
      }
      i2 += String.fromCodePoint(consumeEscapedCodePoint(n2, o2));
    }
  }
}
function checkIfCodePointsMatchURLIdent(e2) {
  return !(3 !== e2.length || 117 !== e2[0] && 85 !== e2[0] || 114 !== e2[1] && 82 !== e2[1] || 108 !== e2[2] && 76 !== e2[2]);
}
function consumeBadURL(e2, n2) {
  for (; ; ) {
    const t2 = n2.source.codePointAt(n2.cursor);
    if (void 0 === t2) return;
    if (41 === t2) return void n2.advanceCodePoint();
    checkIfTwoCodePointsAreAValidEscape(n2) ? (n2.advanceCodePoint(), consumeEscapedCodePoint(e2, n2)) : n2.advanceCodePoint();
  }
}
function consumeUrlToken(n2, t2) {
  for (; isWhitespace(t2.source.codePointAt(t2.cursor) ?? -1); ) t2.advanceCodePoint();
  let o2 = "";
  for (; ; ) {
    if (void 0 === t2.source.codePointAt(t2.cursor)) {
      const r3 = [c.URL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, { value: o2 }];
      return n2.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInURL, t2.representationStart, t2.representationEnd, ["4.3.6. Consume a url token", "Unexpected EOF"], r3)), r3;
    }
    if (41 === t2.source.codePointAt(t2.cursor)) return t2.advanceCodePoint(), [c.URL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, { value: o2 }];
    if (isWhitespace(t2.source.codePointAt(t2.cursor) ?? -1)) {
      for (t2.advanceCodePoint(); isWhitespace(t2.source.codePointAt(t2.cursor) ?? -1); ) t2.advanceCodePoint();
      if (void 0 === t2.source.codePointAt(t2.cursor)) {
        const r3 = [c.URL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, { value: o2 }];
        return n2.onParseError(new ParseErrorWithToken(e.UnexpectedEOFInURL, t2.representationStart, t2.representationEnd, ["4.3.6. Consume a url token", "Consume as much whitespace as possible", "Unexpected EOF"], r3)), r3;
      }
      return 41 === t2.source.codePointAt(t2.cursor) ? (t2.advanceCodePoint(), [c.URL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, { value: o2 }]) : (consumeBadURL(n2, t2), [c.BadURL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, void 0]);
    }
    const r2 = t2.source.codePointAt(t2.cursor);
    if (34 === r2 || 39 === r2 || 40 === r2 || isNonPrintableCodePoint(r2 ?? -1)) {
      consumeBadURL(n2, t2);
      const o3 = [c.BadURL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, void 0];
      return n2.onParseError(new ParseErrorWithToken(e.UnexpectedCharacterInURL, t2.representationStart, t2.representationEnd, ["4.3.6. Consume a url token", `Unexpected U+0022 QUOTATION MARK ("), U+0027 APOSTROPHE ('), U+0028 LEFT PARENTHESIS (() or non-printable code point`], o3)), o3;
    }
    if (92 === r2) {
      if (checkIfTwoCodePointsAreAValidEscape(t2)) {
        t2.advanceCodePoint(), o2 += String.fromCodePoint(consumeEscapedCodePoint(n2, t2));
        continue;
      }
      consumeBadURL(n2, t2);
      const r3 = [c.BadURL, t2.source.slice(t2.representationStart, t2.representationEnd + 1), t2.representationStart, t2.representationEnd, void 0];
      return n2.onParseError(new ParseErrorWithToken(e.InvalidEscapeSequenceInURL, t2.representationStart, t2.representationEnd, ["4.3.6. Consume a url token", "U+005C REVERSE SOLIDUS (\\)", "The input stream does not start with a valid escape sequence"], r3)), r3;
    }
    0 === t2.source.codePointAt(t2.cursor) || isSurrogate(t2.source.codePointAt(t2.cursor) ?? -1) ? (o2 += String.fromCodePoint(s), t2.advanceCodePoint()) : (o2 += t2.source[t2.cursor], t2.advanceCodePoint());
  }
}
function consumeIdentLikeToken(e2, n2) {
  const t2 = consumeIdentSequence(e2, n2);
  if (40 !== n2.source.codePointAt(n2.cursor)) return [c.Ident, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: String.fromCodePoint(...t2) }];
  if (checkIfCodePointsMatchURLIdent(t2)) {
    n2.advanceCodePoint();
    let o2 = 0;
    for (; ; ) {
      const e3 = isWhitespace(n2.source.codePointAt(n2.cursor) ?? -1), r2 = isWhitespace(n2.source.codePointAt(n2.cursor + 1) ?? -1);
      if (e3 && r2) {
        o2 += 1, n2.advanceCodePoint(1);
        continue;
      }
      const i2 = e3 ? n2.source.codePointAt(n2.cursor + 1) : n2.source.codePointAt(n2.cursor);
      if (34 === i2 || 39 === i2) return o2 > 0 && n2.unreadCodePoint(o2), [c.Function, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: String.fromCodePoint(...t2) }];
      break;
    }
    return consumeUrlToken(e2, n2);
  }
  return n2.advanceCodePoint(), [c.Function, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { value: String.fromCodePoint(...t2) }];
}
function checkIfThreeCodePointsWouldStartAUnicodeRange(e2) {
  return !(117 !== e2.source.codePointAt(e2.cursor) && 85 !== e2.source.codePointAt(e2.cursor) || e2.source.codePointAt(e2.cursor + 1) !== i || 63 !== e2.source.codePointAt(e2.cursor + 2) && !isHexDigitCodePoint(e2.source.codePointAt(e2.cursor + 2) ?? -1));
}
function consumeUnicodeRangeToken(e2, n2) {
  n2.advanceCodePoint(2);
  const t2 = [], r2 = [];
  let i2;
  for (; void 0 !== (i2 = n2.source.codePointAt(n2.cursor)) && t2.length < 6 && isHexDigitCodePoint(i2); ) t2.push(i2), n2.advanceCodePoint();
  for (; void 0 !== (i2 = n2.source.codePointAt(n2.cursor)) && t2.length < 6 && 63 === i2; ) 0 === r2.length && r2.push(...t2), t2.push(48), r2.push(70), n2.advanceCodePoint();
  if (!r2.length && n2.source.codePointAt(n2.cursor) === o && isHexDigitCodePoint(n2.source.codePointAt(n2.cursor + 1) ?? -1)) for (n2.advanceCodePoint(); void 0 !== (i2 = n2.source.codePointAt(n2.cursor)) && r2.length < 6 && isHexDigitCodePoint(i2); ) r2.push(i2), n2.advanceCodePoint();
  if (!r2.length) {
    const e3 = parseInt(String.fromCodePoint(...t2), 16);
    return [c.UnicodeRange, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { startOfRange: e3, endOfRange: e3 }];
  }
  const s2 = parseInt(String.fromCodePoint(...t2), 16), a2 = parseInt(String.fromCodePoint(...r2), 16);
  return [c.UnicodeRange, n2.source.slice(n2.representationStart, n2.representationEnd + 1), n2.representationStart, n2.representationEnd, { startOfRange: s2, endOfRange: a2 }];
}
function tokenize(e2, n2) {
  const t2 = tokenizer(e2, n2), o2 = [];
  for (; !t2.endOfFile(); ) o2.push(t2.nextToken());
  return o2.push(t2.nextToken()), o2;
}
function tokenizer(n2, s2) {
  const a2 = n2.css.valueOf(), u2 = n2.unicodeRangesAllowed ?? false, d2 = new Reader(a2), p = { onParseError: s2?.onParseError ?? noop };
  return { nextToken: function nextToken() {
    d2.resetRepresentation();
    const n3 = d2.source.codePointAt(d2.cursor);
    if (void 0 === n3) return [c.EOF, "", -1, -1, void 0];
    if (47 === n3 && checkIfTwoCodePointsStartAComment(d2)) return consumeComment(p, d2);
    if (u2 && (117 === n3 || 85 === n3) && checkIfThreeCodePointsWouldStartAUnicodeRange(d2)) return consumeUnicodeRangeToken(0, d2);
    if (isIdentStartCodePoint(n3)) return consumeIdentLikeToken(p, d2);
    if (isDigitCodePoint(n3)) return consumeNumericToken(p, d2);
    switch (n3) {
      case 44:
        return d2.advanceCodePoint(), [c.Comma, ",", d2.representationStart, d2.representationEnd, void 0];
      case 58:
        return d2.advanceCodePoint(), [c.Colon, ":", d2.representationStart, d2.representationEnd, void 0];
      case 59:
        return d2.advanceCodePoint(), [c.Semicolon, ";", d2.representationStart, d2.representationEnd, void 0];
      case 40:
        return d2.advanceCodePoint(), [c.OpenParen, "(", d2.representationStart, d2.representationEnd, void 0];
      case 41:
        return d2.advanceCodePoint(), [c.CloseParen, ")", d2.representationStart, d2.representationEnd, void 0];
      case 91:
        return d2.advanceCodePoint(), [c.OpenSquare, "[", d2.representationStart, d2.representationEnd, void 0];
      case 93:
        return d2.advanceCodePoint(), [c.CloseSquare, "]", d2.representationStart, d2.representationEnd, void 0];
      case 123:
        return d2.advanceCodePoint(), [c.OpenCurly, "{", d2.representationStart, d2.representationEnd, void 0];
      case 125:
        return d2.advanceCodePoint(), [c.CloseCurly, "}", d2.representationStart, d2.representationEnd, void 0];
      case 39:
      case 34:
        return consumeStringToken(p, d2);
      case 35:
        return consumeHashToken(p, d2);
      case i:
      case 46:
        return checkIfThreeCodePointsWouldStartANumber(d2) ? consumeNumericToken(p, d2) : (d2.advanceCodePoint(), [c.Delim, d2.source[d2.representationStart], d2.representationStart, d2.representationEnd, { value: d2.source[d2.representationStart] }]);
      case r:
      case t:
      case 12:
      case 9:
      case 32:
        return consumeWhiteSpace(d2);
      case o:
        return checkIfThreeCodePointsWouldStartANumber(d2) ? consumeNumericToken(p, d2) : checkIfThreeCodePointsWouldStartCDC(d2) ? (d2.advanceCodePoint(3), [c.CDC, "-->", d2.representationStart, d2.representationEnd, void 0]) : checkIfThreeCodePointsWouldStartAnIdentSequence(0, d2) ? consumeIdentLikeToken(p, d2) : (d2.advanceCodePoint(), [c.Delim, "-", d2.representationStart, d2.representationEnd, { value: "-" }]);
      case 60:
        return checkIfFourCodePointsWouldStartCDO(d2) ? (d2.advanceCodePoint(4), [c.CDO, "<!--", d2.representationStart, d2.representationEnd, void 0]) : (d2.advanceCodePoint(), [c.Delim, "<", d2.representationStart, d2.representationEnd, { value: "<" }]);
      case 64:
        if (d2.advanceCodePoint(), checkIfThreeCodePointsWouldStartAnIdentSequence(0, d2)) {
          const e2 = consumeIdentSequence(p, d2);
          return [c.AtKeyword, d2.source.slice(d2.representationStart, d2.representationEnd + 1), d2.representationStart, d2.representationEnd, { value: String.fromCodePoint(...e2) }];
        }
        return [c.Delim, "@", d2.representationStart, d2.representationEnd, { value: "@" }];
      case 92: {
        if (checkIfTwoCodePointsAreAValidEscape(d2)) return consumeIdentLikeToken(p, d2);
        d2.advanceCodePoint();
        const n4 = [c.Delim, "\\", d2.representationStart, d2.representationEnd, { value: "\\" }];
        return p.onParseError(new ParseErrorWithToken(e.InvalidEscapeSequenceAfterBackslash, d2.representationStart, d2.representationEnd, ["4.3.1. Consume a token", "U+005C REVERSE SOLIDUS (\\)", "The input stream does not start with a valid escape sequence"], n4)), n4;
      }
    }
    return d2.advanceCodePoint(), [c.Delim, d2.source[d2.representationStart], d2.representationStart, d2.representationEnd, { value: d2.source[d2.representationStart] }];
  }, endOfFile: function endOfFile() {
    return void 0 === d2.source.codePointAt(d2.cursor);
  } };
}
function noop() {
}
function mutateIdent(e2, n2) {
  const t2 = [];
  for (const e3 of n2) t2.push(e3.codePointAt(0));
  const o2 = String.fromCodePoint(...serializeIdent(t2));
  e2[1] = o2, e2[4].value = n2;
}
function mutateUnit(e2, n2) {
  const t2 = [];
  for (const e3 of n2) t2.push(e3.codePointAt(0));
  const o2 = serializeIdent(t2);
  101 === o2[0] && insertEscapedCodePoint(o2, 0, o2[0]);
  const r2 = String.fromCodePoint(...o2), i2 = "+" === e2[4].signCharacter ? e2[4].signCharacter : "", s2 = e2[4].value.toString();
  e2[1] = `${i2}${s2}${r2}`, e2[4].unit = n2;
}
function serializeIdent(e2) {
  let n2 = 0;
  if (0 === e2[0]) e2.splice(0, 1, s), n2 = 1;
  else if (e2[0] === o && e2[1] === o) n2 = 2;
  else if (e2[0] === o && e2[1]) n2 = 2, isIdentStartCodePoint(e2[1]) || (n2 += insertEscapedCodePoint(e2, 1, e2[1]));
  else {
    if (e2[0] === o && !e2[1]) return [92, e2[0]];
    isIdentStartCodePoint(e2[0]) ? n2 = 1 : (n2 = 1, n2 += insertEscapedCodePoint(e2, 0, e2[0]));
  }
  for (let t2 = n2; t2 < e2.length; t2++) 0 !== e2[t2] ? isIdentCodePoint(e2[t2]) || (t2 += insertEscapedCharacter(e2, t2, e2[t2])) : (e2.splice(t2, 1, s), t2++);
  return e2;
}
function insertEscapedCharacter(e2, n2, t2) {
  return e2.splice(n2, 1, 92, t2), 1;
}
function insertEscapedCodePoint(e2, n2, t2) {
  const o2 = t2.toString(16), r2 = [];
  for (const e3 of o2) r2.push(e3.codePointAt(0));
  return e2.splice(n2, 1, 92, ...r2, 32), 1 + r2.length;
}
var d = Object.values(c);
function isToken(e2) {
  return !!Array.isArray(e2) && (!(e2.length < 4) && (!!d.includes(e2[0]) && ("string" == typeof e2[1] && ("number" == typeof e2[2] && "number" == typeof e2[3]))));
}
function isTokenNumeric(e2) {
  if (!e2) return false;
  switch (e2[0]) {
    case c.Dimension:
    case c.Number:
    case c.Percentage:
      return true;
    default:
      return false;
  }
}
function isTokenWhiteSpaceOrComment(e2) {
  if (!e2) return false;
  switch (e2[0]) {
    case c.Whitespace:
    case c.Comment:
      return true;
    default:
      return false;
  }
}
function isTokenAtKeyword(e2) {
  return !!e2 && e2[0] === c.AtKeyword;
}
function isTokenBadString(e2) {
  return !!e2 && e2[0] === c.BadString;
}
function isTokenBadURL(e2) {
  return !!e2 && e2[0] === c.BadURL;
}
function isTokenCDC(e2) {
  return !!e2 && e2[0] === c.CDC;
}
function isTokenCDO(e2) {
  return !!e2 && e2[0] === c.CDO;
}
function isTokenColon(e2) {
  return !!e2 && e2[0] === c.Colon;
}
function isTokenComma(e2) {
  return !!e2 && e2[0] === c.Comma;
}
function isTokenComment(e2) {
  return !!e2 && e2[0] === c.Comment;
}
function isTokenDelim(e2) {
  return !!e2 && e2[0] === c.Delim;
}
function isTokenDimension(e2) {
  return !!e2 && e2[0] === c.Dimension;
}
function isTokenEOF(e2) {
  return !!e2 && e2[0] === c.EOF;
}
function isTokenFunction(e2) {
  return !!e2 && e2[0] === c.Function;
}
function isTokenHash(e2) {
  return !!e2 && e2[0] === c.Hash;
}
function isTokenIdent(e2) {
  return !!e2 && e2[0] === c.Ident;
}
function isTokenNumber(e2) {
  return !!e2 && e2[0] === c.Number;
}
function isTokenPercentage(e2) {
  return !!e2 && e2[0] === c.Percentage;
}
function isTokenSemicolon(e2) {
  return !!e2 && e2[0] === c.Semicolon;
}
function isTokenString(e2) {
  return !!e2 && e2[0] === c.String;
}
function isTokenURL(e2) {
  return !!e2 && e2[0] === c.URL;
}
function isTokenWhitespace(e2) {
  return !!e2 && e2[0] === c.Whitespace;
}
function isTokenOpenParen(e2) {
  return !!e2 && e2[0] === c.OpenParen;
}
function isTokenCloseParen(e2) {
  return !!e2 && e2[0] === c.CloseParen;
}
function isTokenOpenSquare(e2) {
  return !!e2 && e2[0] === c.OpenSquare;
}
function isTokenCloseSquare(e2) {
  return !!e2 && e2[0] === c.CloseSquare;
}
function isTokenOpenCurly(e2) {
  return !!e2 && e2[0] === c.OpenCurly;
}
function isTokenCloseCurly(e2) {
  return !!e2 && e2[0] === c.CloseCurly;
}
function isTokenUnicodeRange(e2) {
  return !!e2 && e2[0] === c.UnicodeRange;
}

// node_modules/@csstools/css-parser-algorithms/dist/index.mjs
var f;
function walkerIndexGenerator(e2) {
  let n2 = e2.slice();
  return (e3, t2, o2) => {
    let s2 = -1;
    for (let i2 = n2.indexOf(t2); i2 < n2.length && (s2 = e3.indexOf(n2[i2]), -1 === s2 || s2 < o2); i2++) ;
    return -1 === s2 || s2 === o2 && t2 === e3[o2] && (s2++, s2 >= e3.length) ? -1 : (n2 = e3.slice(), s2);
  };
}
function consumeComponentValue(e2, n2) {
  const t2 = n2[0];
  if (isTokenOpenParen(t2) || isTokenOpenCurly(t2) || isTokenOpenSquare(t2)) {
    const t3 = consumeSimpleBlock(e2, n2);
    return { advance: t3.advance, node: t3.node };
  }
  if (isTokenFunction(t2)) {
    const t3 = consumeFunction(e2, n2);
    return { advance: t3.advance, node: t3.node };
  }
  if (isTokenWhitespace(t2)) {
    const t3 = consumeWhitespace(e2, n2);
    return { advance: t3.advance, node: t3.node };
  }
  if (isTokenComment(t2)) {
    const t3 = consumeComment2(e2, n2);
    return { advance: t3.advance, node: t3.node };
  }
  return { advance: 1, node: new TokenNode(t2) };
}
!function(e2) {
  e2.Function = "function", e2.SimpleBlock = "simple-block", e2.Whitespace = "whitespace", e2.Comment = "comment", e2.Token = "token";
}(f || (f = {}));
var ContainerNodeBaseClass = class {
  value = [];
  indexOf(e2) {
    return this.value.indexOf(e2);
  }
  at(e2) {
    if ("number" == typeof e2) return e2 < 0 && (e2 = this.value.length + e2), this.value[e2];
  }
  forEach(e2, n2) {
    if (0 === this.value.length) return;
    const t2 = walkerIndexGenerator(this.value);
    let o2 = 0;
    for (; o2 < this.value.length; ) {
      const s2 = this.value[o2];
      let i2;
      if (n2 && (i2 = { ...n2 }), false === e2({ node: s2, parent: this, state: i2 }, o2)) return false;
      if (o2 = t2(this.value, s2, o2), -1 === o2) break;
    }
  }
  walk(e2, n2) {
    0 !== this.value.length && this.forEach((n3, t2) => false !== e2(n3, t2) && ((!("walk" in n3.node) || !this.value.includes(n3.node) || false !== n3.node.walk(e2, n3.state)) && void 0), n2);
  }
};
var FunctionNode = class _FunctionNode extends ContainerNodeBaseClass {
  type = f.Function;
  name;
  endToken;
  constructor(e2, n2, t2) {
    super(), this.name = e2, this.endToken = n2, this.value = t2;
  }
  getName() {
    return this.name[4].value;
  }
  normalize() {
    isTokenEOF(this.endToken) && (this.endToken = [c.CloseParen, ")", -1, -1, void 0]);
  }
  tokens() {
    return isTokenEOF(this.endToken) ? [this.name, ...this.value.flatMap((e2) => e2.tokens())] : [this.name, ...this.value.flatMap((e2) => e2.tokens()), this.endToken];
  }
  toString() {
    const e2 = this.value.map((e3) => isToken(e3) ? stringify(e3) : e3.toString()).join("");
    return stringify(this.name) + e2 + stringify(this.endToken);
  }
  toJSON() {
    return { type: this.type, name: this.getName(), tokens: this.tokens(), value: this.value.map((e2) => e2.toJSON()) };
  }
  isFunctionNode() {
    return _FunctionNode.isFunctionNode(this);
  }
  static isFunctionNode(e2) {
    return !!e2 && (e2 instanceof _FunctionNode && e2.type === f.Function);
  }
};
function consumeFunction(n2, t2) {
  const o2 = [];
  let s2 = 1;
  for (; ; ) {
    const i2 = t2[s2];
    if (!i2 || isTokenEOF(i2)) return n2.onParseError(new ParseError("Unexpected EOF while consuming a function.", t2[0][2], t2[t2.length - 1][3], ["5.4.9. Consume a function", "Unexpected EOF"])), { advance: t2.length, node: new FunctionNode(t2[0], i2, o2) };
    if (isTokenCloseParen(i2)) return { advance: s2 + 1, node: new FunctionNode(t2[0], i2, o2) };
    if (isTokenWhiteSpaceOrComment(i2)) {
      const e2 = consumeAllCommentsAndWhitespace(n2, t2.slice(s2));
      s2 += e2.advance, o2.push(...e2.nodes);
      continue;
    }
    const r2 = consumeComponentValue(n2, t2.slice(s2));
    s2 += r2.advance, o2.push(r2.node);
  }
}
var SimpleBlockNode = class _SimpleBlockNode extends ContainerNodeBaseClass {
  type = f.SimpleBlock;
  startToken;
  endToken;
  constructor(e2, n2, t2) {
    super(), this.startToken = e2, this.endToken = n2, this.value = t2;
  }
  normalize() {
    if (isTokenEOF(this.endToken)) {
      const e2 = mirrorVariant(this.startToken);
      e2 && (this.endToken = e2);
    }
  }
  tokens() {
    return isTokenEOF(this.endToken) ? [this.startToken, ...this.value.flatMap((e2) => e2.tokens())] : [this.startToken, ...this.value.flatMap((e2) => e2.tokens()), this.endToken];
  }
  toString() {
    const e2 = this.value.map((e3) => isToken(e3) ? stringify(e3) : e3.toString()).join("");
    return stringify(this.startToken) + e2 + stringify(this.endToken);
  }
  toJSON() {
    return { type: this.type, startToken: this.startToken, tokens: this.tokens(), value: this.value.map((e2) => e2.toJSON()) };
  }
  isSimpleBlockNode() {
    return _SimpleBlockNode.isSimpleBlockNode(this);
  }
  static isSimpleBlockNode(e2) {
    return !!e2 && (e2 instanceof _SimpleBlockNode && e2.type === f.SimpleBlock);
  }
};
function consumeSimpleBlock(n2, t2) {
  const o2 = mirrorVariantType(t2[0][0]);
  if (!o2) throw new Error("Failed to parse, a mirror variant must exist for all block open tokens.");
  const s2 = [];
  let i2 = 1;
  for (; ; ) {
    const r2 = t2[i2];
    if (!r2 || isTokenEOF(r2)) return n2.onParseError(new ParseError("Unexpected EOF while consuming a simple block.", t2[0][2], t2[t2.length - 1][3], ["5.4.8. Consume a simple block", "Unexpected EOF"])), { advance: t2.length, node: new SimpleBlockNode(t2[0], r2, s2) };
    if (r2[0] === o2) return { advance: i2 + 1, node: new SimpleBlockNode(t2[0], r2, s2) };
    if (isTokenWhiteSpaceOrComment(r2)) {
      const e2 = consumeAllCommentsAndWhitespace(n2, t2.slice(i2));
      i2 += e2.advance, s2.push(...e2.nodes);
      continue;
    }
    const a2 = consumeComponentValue(n2, t2.slice(i2));
    i2 += a2.advance, s2.push(a2.node);
  }
}
var WhitespaceNode = class _WhitespaceNode {
  type = f.Whitespace;
  value;
  constructor(e2) {
    this.value = e2;
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
  static isWhitespaceNode(e2) {
    return !!e2 && (e2 instanceof _WhitespaceNode && e2.type === f.Whitespace);
  }
};
function consumeWhitespace(e2, n2) {
  let t2 = 0;
  for (; ; ) {
    const e3 = n2[t2];
    if (!isTokenWhitespace(e3)) return { advance: t2, node: new WhitespaceNode(n2.slice(0, t2)) };
    t2++;
  }
}
var CommentNode = class _CommentNode {
  type = f.Comment;
  value;
  constructor(e2) {
    this.value = e2;
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
  static isCommentNode(e2) {
    return !!e2 && (e2 instanceof _CommentNode && e2.type === f.Comment);
  }
};
function consumeComment2(e2, n2) {
  return { advance: 1, node: new CommentNode(n2[0]) };
}
function consumeAllCommentsAndWhitespace(e2, n2) {
  const t2 = [];
  let o2 = 0;
  for (; ; ) {
    if (isTokenWhitespace(n2[o2])) {
      const e3 = consumeWhitespace(0, n2.slice(o2));
      o2 += e3.advance, t2.push(e3.node);
      continue;
    }
    if (!isTokenComment(n2[o2])) return { advance: o2, nodes: t2 };
    t2.push(new CommentNode(n2[o2])), o2++;
  }
}
var TokenNode = class _TokenNode {
  type = f.Token;
  value;
  constructor(e2) {
    this.value = e2;
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
  static isTokenNode(e2) {
    return !!e2 && (e2 instanceof _TokenNode && e2.type === f.Token);
  }
};
function parseComponentValue(t2, o2) {
  const s2 = { onParseError: o2?.onParseError ?? (() => {
  }) }, i2 = [...t2];
  isTokenEOF(i2[i2.length - 1]) || i2.push([c.EOF, "", i2[i2.length - 1][2], i2[i2.length - 1][3], void 0]);
  const r2 = consumeComponentValue(s2, i2);
  if (isTokenEOF(i2[Math.min(r2.advance, i2.length - 1)])) return r2.node;
  s2.onParseError(new ParseError("Expected EOF after parsing a component value.", t2[0][2], t2[t2.length - 1][3], ["5.3.9. Parse a component value", "Expected EOF"]));
}
function parseListOfComponentValues(t2, o2) {
  const s2 = { onParseError: o2?.onParseError ?? (() => {
  }) }, i2 = [...t2];
  isTokenEOF(i2[i2.length - 1]) && i2.push([c.EOF, "", i2[i2.length - 1][2], i2[i2.length - 1][3], void 0]);
  const r2 = [];
  let a2 = 0;
  for (; ; ) {
    if (!i2[a2] || isTokenEOF(i2[a2])) return r2;
    const n2 = consumeComponentValue(s2, i2.slice(a2));
    r2.push(n2.node), a2 += n2.advance;
  }
}
function parseCommaSeparatedListOfComponentValues(t2, o2) {
  const s2 = { onParseError: o2?.onParseError ?? (() => {
  }) }, i2 = [...t2];
  if (0 === t2.length) return [];
  isTokenEOF(i2[i2.length - 1]) && i2.push([c.EOF, "", i2[i2.length - 1][2], i2[i2.length - 1][3], void 0]);
  const r2 = [];
  let a2 = [], c2 = 0;
  for (; ; ) {
    if (!i2[c2] || isTokenEOF(i2[c2])) return a2.length && r2.push(a2), r2;
    if (isTokenComma(i2[c2])) {
      r2.push(a2), a2 = [], c2++;
      continue;
    }
    const n2 = consumeComponentValue(s2, t2.slice(c2));
    a2.push(n2.node), c2 += n2.advance;
  }
}
function gatherNodeAncestry(e2) {
  const n2 = /* @__PURE__ */ new Map();
  return e2.walk((e3) => {
    Array.isArray(e3.node) ? e3.node.forEach((t2) => {
      n2.set(t2, e3.parent);
    }) : n2.set(e3.node, e3.parent);
  }), n2;
}
function forEach(e2, n2, t2) {
  if (0 === e2.length) return;
  const o2 = walkerIndexGenerator(e2);
  let s2 = 0;
  for (; s2 < e2.length; ) {
    const i2 = e2[s2];
    let r2;
    if (t2 && (r2 = { ...t2 }), false === n2({ node: i2, parent: { value: e2 }, state: r2 }, s2)) return false;
    if (s2 = o2(e2, i2, s2), -1 === s2) break;
  }
}
function walk(e2, n2, t2) {
  0 !== e2.length && forEach(e2, (t3, o2) => false !== n2(t3, o2) && ((!("walk" in t3.node) || !e2.includes(t3.node) || false !== t3.node.walk(n2, t3.state)) && void 0), t2);
}
function replaceComponentValues(e2, n2) {
  for (let t2 = 0; t2 < e2.length; t2++) {
    walk(e2[t2], (e3, t3) => {
      if ("number" != typeof t3) return;
      const o2 = n2(e3.node);
      o2 && (Array.isArray(o2) ? e3.parent.value.splice(t3, 1, ...o2) : e3.parent.value.splice(t3, 1, o2));
    });
  }
  return e2;
}
function stringify2(e2) {
  return e2.map((e3) => e3.map((e4) => stringify(...e4.tokens())).join("")).join(",");
}
function isSimpleBlockNode(e2) {
  return SimpleBlockNode.isSimpleBlockNode(e2);
}
function isFunctionNode(e2) {
  return FunctionNode.isFunctionNode(e2);
}
function isWhitespaceNode(e2) {
  return WhitespaceNode.isWhitespaceNode(e2);
}
function isCommentNode(e2) {
  return CommentNode.isCommentNode(e2);
}
function isWhiteSpaceOrCommentNode(e2) {
  return isWhitespaceNode(e2) || isCommentNode(e2);
}
function isTokenNode(e2) {
  return TokenNode.isTokenNode(e2);
}
function sourceIndices(e2) {
  if (Array.isArray(e2)) {
    const n3 = e2[0];
    if (!n3) return [0, 0];
    const t3 = e2[e2.length - 1] || n3;
    return [sourceIndices(n3)[0], sourceIndices(t3)[1]];
  }
  const n2 = e2.tokens(), t2 = n2[0], o2 = n2[n2.length - 1];
  return t2 && o2 ? [t2[2], o2[3]] : [0, 0];
}

// node_modules/@csstools/css-calc/dist/index.mjs
var ParseError2 = class extends Error {
  sourceStart;
  sourceEnd;
  constructor(e2, n2, t2) {
    super(e2), this.name = "ParseError", this.sourceStart = n2, this.sourceEnd = t2;
  }
};
var ParseErrorWithComponentValues = class extends ParseError2 {
  componentValues;
  constructor(n2, t2) {
    super(n2, ...sourceIndices(t2)), this.componentValues = t2;
  }
};
var y = { UnexpectedAdditionOfDimensionOrPercentageWithNumber: "Unexpected addition of a dimension or percentage with a number.", UnexpectedSubtractionOfDimensionOrPercentageWithNumber: "Unexpected subtraction of a dimension or percentage with a number." }, M = /[A-Z]/g;
function toLowerCaseAZ(e2) {
  return e2.replace(M, (e3) => String.fromCharCode(e3.charCodeAt(0) + 32));
}
var T = { cm: "px", in: "px", mm: "px", pc: "px", pt: "px", px: "px", q: "px", deg: "deg", grad: "deg", rad: "deg", turn: "deg", ms: "s", s: "s", hz: "hz", khz: "hz" }, x = /* @__PURE__ */ new Map([["cm", (e2) => e2], ["mm", (e2) => 10 * e2], ["q", (e2) => 40 * e2], ["in", (e2) => e2 / 2.54], ["pc", (e2) => e2 / 2.54 * 6], ["pt", (e2) => e2 / 2.54 * 72], ["px", (e2) => e2 / 2.54 * 96]]), P = /* @__PURE__ */ new Map([["deg", (e2) => e2], ["grad", (e2) => e2 / 0.9], ["rad", (e2) => e2 / 180 * Math.PI], ["turn", (e2) => e2 / 360]]), k = /* @__PURE__ */ new Map([["deg", (e2) => 0.9 * e2], ["grad", (e2) => e2], ["rad", (e2) => 0.9 * e2 / 180 * Math.PI], ["turn", (e2) => 0.9 * e2 / 360]]), O = /* @__PURE__ */ new Map([["hz", (e2) => e2], ["khz", (e2) => e2 / 1e3]]), W = /* @__PURE__ */ new Map([["cm", (e2) => 2.54 * e2], ["mm", (e2) => 25.4 * e2], ["q", (e2) => 25.4 * e2 * 4], ["in", (e2) => e2], ["pc", (e2) => 6 * e2], ["pt", (e2) => 72 * e2], ["px", (e2) => 96 * e2]]), U = /* @__PURE__ */ new Map([["hz", (e2) => 1e3 * e2], ["khz", (e2) => e2]]), L = /* @__PURE__ */ new Map([["cm", (e2) => e2 / 10], ["mm", (e2) => e2], ["q", (e2) => 4 * e2], ["in", (e2) => e2 / 25.4], ["pc", (e2) => e2 / 25.4 * 6], ["pt", (e2) => e2 / 25.4 * 72], ["px", (e2) => e2 / 25.4 * 96]]), V = /* @__PURE__ */ new Map([["ms", (e2) => e2], ["s", (e2) => e2 / 1e3]]), $ = /* @__PURE__ */ new Map([["cm", (e2) => e2 / 6 * 2.54], ["mm", (e2) => e2 / 6 * 25.4], ["q", (e2) => e2 / 6 * 25.4 * 4], ["in", (e2) => e2 / 6], ["pc", (e2) => e2], ["pt", (e2) => e2 / 6 * 72], ["px", (e2) => e2 / 6 * 96]]), Z = /* @__PURE__ */ new Map([["cm", (e2) => e2 / 72 * 2.54], ["mm", (e2) => e2 / 72 * 25.4], ["q", (e2) => e2 / 72 * 25.4 * 4], ["in", (e2) => e2 / 72], ["pc", (e2) => e2 / 72 * 6], ["pt", (e2) => e2], ["px", (e2) => e2 / 72 * 96]]), z = /* @__PURE__ */ new Map([["cm", (e2) => e2 / 96 * 2.54], ["mm", (e2) => e2 / 96 * 25.4], ["q", (e2) => e2 / 96 * 25.4 * 4], ["in", (e2) => e2 / 96], ["pc", (e2) => e2 / 96 * 6], ["pt", (e2) => e2 / 96 * 72], ["px", (e2) => e2]]), q = /* @__PURE__ */ new Map([["cm", (e2) => e2 / 4 / 10], ["mm", (e2) => e2 / 4], ["q", (e2) => e2], ["in", (e2) => e2 / 4 / 25.4], ["pc", (e2) => e2 / 4 / 25.4 * 6], ["pt", (e2) => e2 / 4 / 25.4 * 72], ["px", (e2) => e2 / 4 / 25.4 * 96]]), G = /* @__PURE__ */ new Map([["deg", (e2) => 180 * e2 / Math.PI], ["grad", (e2) => 180 * e2 / Math.PI / 0.9], ["rad", (e2) => e2], ["turn", (e2) => 180 * e2 / Math.PI / 360]]), R = /* @__PURE__ */ new Map([["ms", (e2) => 1e3 * e2], ["s", (e2) => e2]]), j = /* @__PURE__ */ new Map([["deg", (e2) => 360 * e2], ["grad", (e2) => 360 * e2 / 0.9], ["rad", (e2) => 360 * e2 / 180 * Math.PI], ["turn", (e2) => e2]]), Y = /* @__PURE__ */ new Map([["cm", x], ["mm", L], ["q", q], ["in", W], ["pc", $], ["pt", Z], ["px", z], ["ms", V], ["s", R], ["deg", P], ["grad", k], ["rad", G], ["turn", j], ["hz", O], ["khz", U]]);
function convertUnit(e2, n2) {
  if (!isTokenDimension(e2)) return n2;
  if (!isTokenDimension(n2)) return n2;
  const t2 = toLowerCaseAZ(e2[4].unit), r2 = toLowerCaseAZ(n2[4].unit);
  if (t2 === r2) return n2;
  const a2 = Y.get(r2);
  if (!a2) return n2;
  const u2 = a2.get(t2);
  if (!u2) return n2;
  const o2 = u2(n2[4].value), i2 = [c.Dimension, "", n2[2], n2[3], { ...n2[4], signCharacter: o2 < 0 ? "-" : void 0, type: Number.isInteger(o2) ? a.Integer : a.Number, value: o2 }];
  return mutateUnit(i2, e2[4].unit), i2;
}
function toCanonicalUnit(e2) {
  if (!isTokenDimension(e2)) return e2;
  const n2 = toLowerCaseAZ(e2[4].unit), t2 = T[n2];
  if (n2 === t2) return e2;
  const r2 = Y.get(n2);
  if (!r2) return e2;
  const a2 = r2.get(t2);
  if (!a2) return e2;
  const u2 = a2(e2[4].value), o2 = [c.Dimension, "", e2[2], e2[3], { ...e2[4], signCharacter: u2 < 0 ? "-" : void 0, type: Number.isInteger(u2) ? a.Integer : a.Number, value: u2 }];
  return mutateUnit(o2, t2), o2;
}
function addition(e2, t2) {
  if (2 !== e2.length) return -1;
  const r2 = e2[0].value;
  let a2 = e2[1].value;
  if (isTokenNumber(r2) && isTokenNumber(a2)) {
    const e3 = r2[4].value + a2[4].value;
    return new TokenNode([c.Number, e3.toString(), r2[2], a2[3], { value: e3, type: r2[4].type === a.Integer && a2[4].type === a.Integer ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(r2) && isTokenPercentage(a2)) {
    const e3 = r2[4].value + a2[4].value;
    return new TokenNode([c.Percentage, e3.toString() + "%", r2[2], a2[3], { value: e3 }]);
  }
  if (isTokenDimension(r2) && isTokenDimension(a2) && (a2 = convertUnit(r2, a2), toLowerCaseAZ(r2[4].unit) === toLowerCaseAZ(a2[4].unit))) {
    const e3 = r2[4].value + a2[4].value;
    return new TokenNode([c.Dimension, e3.toString() + r2[4].unit, r2[2], a2[3], { value: e3, type: r2[4].type === a.Integer && a2[4].type === a.Integer ? a.Integer : a.Number, unit: r2[4].unit }]);
  }
  return (isTokenNumber(r2) && (isTokenDimension(a2) || isTokenPercentage(a2)) || isTokenNumber(a2) && (isTokenDimension(r2) || isTokenPercentage(r2))) && t2.onParseError?.(new ParseErrorWithComponentValues(y.UnexpectedAdditionOfDimensionOrPercentageWithNumber, e2)), -1;
}
function division(e2) {
  if (2 !== e2.length) return -1;
  const t2 = e2[0].value, r2 = e2[1].value;
  if (isTokenNumber(t2) && isTokenNumber(r2)) {
    const e3 = t2[4].value / r2[4].value;
    return new TokenNode([c.Number, e3.toString(), t2[2], r2[3], { value: e3, type: Number.isInteger(e3) ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(t2) && isTokenNumber(r2)) {
    const e3 = t2[4].value / r2[4].value;
    return new TokenNode([c.Percentage, e3.toString() + "%", t2[2], r2[3], { value: e3 }]);
  }
  if (isTokenDimension(t2) && isTokenNumber(r2)) {
    const e3 = t2[4].value / r2[4].value;
    return new TokenNode([c.Dimension, e3.toString() + t2[4].unit, t2[2], r2[3], { value: e3, type: Number.isInteger(e3) ? a.Integer : a.Number, unit: t2[4].unit }]);
  }
  return -1;
}
function isCalculation(e2) {
  return !!e2 && "object" == typeof e2 && "inputs" in e2 && Array.isArray(e2.inputs) && "operation" in e2;
}
function solve(e2, n2) {
  if (-1 === e2) return -1;
  const r2 = [];
  for (let a2 = 0; a2 < e2.inputs.length; a2++) {
    const u2 = e2.inputs[a2];
    if (isTokenNode(u2)) {
      r2.push(u2);
      continue;
    }
    const o2 = solve(u2, n2);
    if (-1 === o2) return -1;
    r2.push(o2);
  }
  return e2.operation(r2, n2);
}
function multiplication(e2) {
  if (2 !== e2.length) return -1;
  const t2 = e2[0].value, r2 = e2[1].value;
  if (isTokenNumber(t2) && isTokenNumber(r2)) {
    const e3 = t2[4].value * r2[4].value;
    return new TokenNode([c.Number, e3.toString(), t2[2], r2[3], { value: e3, type: t2[4].type === a.Integer && r2[4].type === a.Integer ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(t2) && isTokenNumber(r2)) {
    const e3 = t2[4].value * r2[4].value;
    return new TokenNode([c.Percentage, e3.toString() + "%", t2[2], r2[3], { value: e3 }]);
  }
  if (isTokenNumber(t2) && isTokenPercentage(r2)) {
    const e3 = t2[4].value * r2[4].value;
    return new TokenNode([c.Percentage, e3.toString() + "%", t2[2], r2[3], { value: e3 }]);
  }
  if (isTokenDimension(t2) && isTokenNumber(r2)) {
    const e3 = t2[4].value * r2[4].value;
    return new TokenNode([c.Dimension, e3.toString() + t2[4].unit, t2[2], r2[3], { value: e3, type: t2[4].type === a.Integer && r2[4].type === a.Integer ? a.Integer : a.Number, unit: t2[4].unit }]);
  }
  if (isTokenNumber(t2) && isTokenDimension(r2)) {
    const e3 = t2[4].value * r2[4].value;
    return new TokenNode([c.Dimension, e3.toString() + r2[4].unit, t2[2], r2[3], { value: e3, type: t2[4].type === a.Integer && r2[4].type === a.Integer ? a.Integer : a.Number, unit: r2[4].unit }]);
  }
  return -1;
}
function resolveGlobalsAndConstants(e2, r2) {
  for (let a2 = 0; a2 < e2.length; a2++) {
    const u2 = e2[a2];
    if (!isTokenNode(u2)) continue;
    const o2 = u2.value;
    if (!isTokenIdent(o2)) continue;
    const i2 = toLowerCaseAZ(o2[4].value);
    switch (i2) {
      case "e":
        e2.splice(a2, 1, new TokenNode([c.Number, Math.E.toString(), o2[2], o2[3], { value: Math.E, type: a.Number }]));
        break;
      case "pi":
        e2.splice(a2, 1, new TokenNode([c.Number, Math.PI.toString(), o2[2], o2[3], { value: Math.PI, type: a.Number }]));
        break;
      case "infinity":
        e2.splice(a2, 1, new TokenNode([c.Number, "infinity", o2[2], o2[3], { value: 1 / 0, type: a.Number }]));
        break;
      case "-infinity":
        e2.splice(a2, 1, new TokenNode([c.Number, "-infinity", o2[2], o2[3], { value: -1 / 0, type: a.Number }]));
        break;
      case "nan":
        e2.splice(a2, 1, new TokenNode([c.Number, "NaN", o2[2], o2[3], { value: Number.NaN, type: a.Number }]));
        break;
      default:
        if (r2.has(i2)) {
          const t2 = r2.get(i2);
          e2.splice(a2, 1, new TokenNode(t2));
        }
    }
  }
  return e2;
}
function unary(e2) {
  if (1 !== e2.length) return -1;
  const n2 = e2[0].value;
  return isTokenNumeric(n2) ? e2[0] : -1;
}
function resultToCalculation(e2, n2, t2) {
  return isTokenDimension(n2) ? dimensionToCalculation(e2, n2[4].unit, t2) : isTokenPercentage(n2) ? percentageToCalculation(e2, t2) : isTokenNumber(n2) ? numberToCalculation(e2, t2) : -1;
}
function dimensionToCalculation(e2, t2, r2) {
  const a2 = e2.tokens();
  return { inputs: [new TokenNode([c.Dimension, r2.toString() + t2, a2[0][2], a2[a2.length - 1][3], { value: r2, type: Number.isInteger(r2) ? a.Integer : a.Number, unit: t2 }])], operation: unary };
}
function percentageToCalculation(e2, t2) {
  const r2 = e2.tokens();
  return { inputs: [new TokenNode([c.Percentage, t2.toString() + "%", r2[0][2], r2[r2.length - 1][3], { value: t2 }])], operation: unary };
}
function numberToCalculation(e2, t2) {
  const r2 = e2.tokens();
  return { inputs: [new TokenNode([c.Number, t2.toString(), r2[0][2], r2[r2.length - 1][3], { value: t2, type: Number.isInteger(t2) ? a.Integer : a.Number }])], operation: unary };
}
function solveACos(e2, n2) {
  const t2 = n2.value;
  if (!isTokenNumber(t2)) return -1;
  return dimensionToCalculation(e2, "rad", Math.acos(t2[4].value));
}
function solveASin(e2, n2) {
  const t2 = n2.value;
  if (!isTokenNumber(t2)) return -1;
  return dimensionToCalculation(e2, "rad", Math.asin(t2[4].value));
}
function solveATan(e2, n2) {
  const t2 = n2.value;
  if (!isTokenNumber(t2)) return -1;
  return dimensionToCalculation(e2, "rad", Math.atan(t2[4].value));
}
function isDimensionOrNumber(e2) {
  return isTokenDimension(e2) || isTokenNumber(e2);
}
function arrayOfSameNumeric(e2) {
  if (0 === e2.length) return true;
  const n2 = e2[0];
  if (!isTokenNumeric(n2)) return false;
  if (1 === e2.length) return true;
  if (isTokenDimension(n2)) {
    const t2 = toLowerCaseAZ(n2[4].unit);
    for (let r2 = 1; r2 < e2.length; r2++) {
      const a2 = e2[r2];
      if (n2[0] !== a2[0]) return false;
      if (t2 !== toLowerCaseAZ(a2[4].unit)) return false;
    }
    return true;
  }
  for (let t2 = 1; t2 < e2.length; t2++) {
    const r2 = e2[t2];
    if (n2[0] !== r2[0]) return false;
  }
  return true;
}
function twoOfSameNumeric(e2, n2) {
  return !!isTokenNumeric(e2) && (isTokenDimension(e2) ? e2[0] === n2[0] && toLowerCaseAZ(e2[4].unit) === toLowerCaseAZ(n2[4].unit) : e2[0] === n2[0]);
}
function solveATan2(e2, n2, t2) {
  const r2 = n2.value;
  if (!isDimensionOrNumber(r2)) return -1;
  const a2 = convertUnit(r2, t2.value);
  if (!twoOfSameNumeric(r2, a2)) return -1;
  return dimensionToCalculation(e2, "rad", Math.atan2(r2[4].value, a2[4].value));
}
function solveAbs(e2, n2, t2) {
  const r2 = n2.value;
  if (!isTokenNumeric(r2)) return -1;
  if (!t2.rawPercentages && isTokenPercentage(r2)) return -1;
  return resultToCalculation(e2, r2, Math.abs(r2[4].value));
}
function solveClamp(e2, n2, r2, a2, u2) {
  if (!isTokenNode(n2) || !isTokenNode(r2) || !isTokenNode(a2)) return -1;
  const o2 = n2.value;
  if (!isTokenNumeric(o2)) return -1;
  if (!u2.rawPercentages && isTokenPercentage(o2)) return -1;
  const i2 = convertUnit(o2, r2.value);
  if (!twoOfSameNumeric(o2, i2)) return -1;
  const l = convertUnit(o2, a2.value);
  if (!twoOfSameNumeric(o2, l)) return -1;
  return resultToCalculation(e2, o2, Math.max(o2[4].value, Math.min(i2[4].value, l[4].value)));
}
function solveCos(e2, n2) {
  const t2 = n2.value;
  if (!isDimensionOrNumber(t2)) return -1;
  let r2 = t2[4].value;
  if (isTokenDimension(t2)) switch (t2[4].unit.toLowerCase()) {
    case "rad":
      break;
    case "deg":
      r2 = P.get("rad")(t2[4].value);
      break;
    case "grad":
      r2 = k.get("rad")(t2[4].value);
      break;
    case "turn":
      r2 = j.get("rad")(t2[4].value);
      break;
    default:
      return -1;
  }
  return r2 = Math.cos(r2), numberToCalculation(e2, r2);
}
function solveExp(e2, n2) {
  const t2 = n2.value;
  if (!isTokenNumber(t2)) return -1;
  return numberToCalculation(e2, Math.exp(t2[4].value));
}
function solveHypot(e2, n2, r2) {
  if (!n2.every(isTokenNode)) return -1;
  const a2 = n2[0].value;
  if (!isTokenNumeric(a2)) return -1;
  if (!r2.rawPercentages && isTokenPercentage(a2)) return -1;
  const u2 = n2.map((e3) => convertUnit(a2, e3.value));
  if (!arrayOfSameNumeric(u2)) return -1;
  const o2 = u2.map((e3) => e3[4].value), i2 = Math.hypot(...o2);
  return resultToCalculation(e2, a2, i2);
}
function solveMax(e2, n2, r2) {
  if (!n2.every(isTokenNode)) return -1;
  const a2 = n2[0].value;
  if (!isTokenNumeric(a2)) return -1;
  if (!r2.rawPercentages && isTokenPercentage(a2)) return -1;
  const u2 = n2.map((e3) => convertUnit(a2, e3.value));
  if (!arrayOfSameNumeric(u2)) return -1;
  const o2 = u2.map((e3) => e3[4].value), i2 = Math.max(...o2);
  return resultToCalculation(e2, a2, i2);
}
function solveMin(e2, n2, r2) {
  if (!n2.every(isTokenNode)) return -1;
  const a2 = n2[0].value;
  if (!isTokenNumeric(a2)) return -1;
  if (!r2.rawPercentages && isTokenPercentage(a2)) return -1;
  const u2 = n2.map((e3) => convertUnit(a2, e3.value));
  if (!arrayOfSameNumeric(u2)) return -1;
  const o2 = u2.map((e3) => e3[4].value), i2 = Math.min(...o2);
  return resultToCalculation(e2, a2, i2);
}
function solveMod(e2, n2, t2) {
  const r2 = n2.value;
  if (!isTokenNumeric(r2)) return -1;
  const a2 = convertUnit(r2, t2.value);
  if (!twoOfSameNumeric(r2, a2)) return -1;
  let u2;
  return u2 = 0 === a2[4].value ? Number.NaN : Number.isFinite(r2[4].value) && (Number.isFinite(a2[4].value) || (a2[4].value !== Number.POSITIVE_INFINITY || r2[4].value !== Number.NEGATIVE_INFINITY && !Object.is(0 * r2[4].value, -0)) && (a2[4].value !== Number.NEGATIVE_INFINITY || r2[4].value !== Number.POSITIVE_INFINITY && !Object.is(0 * r2[4].value, 0))) ? Number.isFinite(a2[4].value) ? (r2[4].value % a2[4].value + a2[4].value) % a2[4].value : r2[4].value : Number.NaN, resultToCalculation(e2, r2, u2);
}
function solvePow(e2, n2, t2) {
  const r2 = n2.value, a2 = t2.value;
  if (!isTokenNumber(r2)) return -1;
  if (!twoOfSameNumeric(r2, a2)) return -1;
  return numberToCalculation(e2, Math.pow(r2[4].value, a2[4].value));
}
function solveRem(e2, n2, t2) {
  const r2 = n2.value;
  if (!isTokenNumeric(r2)) return -1;
  const a2 = convertUnit(r2, t2.value);
  if (!twoOfSameNumeric(r2, a2)) return -1;
  let u2;
  return u2 = 0 === a2[4].value ? Number.NaN : Number.isFinite(r2[4].value) ? Number.isFinite(a2[4].value) ? r2[4].value % a2[4].value : r2[4].value : Number.NaN, resultToCalculation(e2, r2, u2);
}
function solveRound(e2, n2, t2, r2, a2) {
  const u2 = t2.value;
  if (!isTokenNumeric(u2)) return -1;
  if (!a2.rawPercentages && isTokenPercentage(u2)) return -1;
  const o2 = convertUnit(u2, r2.value);
  if (!twoOfSameNumeric(u2, o2)) return -1;
  let i2;
  if (0 === o2[4].value) i2 = Number.NaN;
  else if (Number.isFinite(u2[4].value) || Number.isFinite(o2[4].value)) if (!Number.isFinite(u2[4].value) && Number.isFinite(o2[4].value)) i2 = u2[4].value;
  else if (Number.isFinite(u2[4].value) && !Number.isFinite(o2[4].value)) switch (n2) {
    case "down":
      i2 = u2[4].value < 0 ? -1 / 0 : Object.is(-0, 0 * u2[4].value) ? -0 : 0;
      break;
    case "up":
      i2 = u2[4].value > 0 ? 1 / 0 : Object.is(0, 0 * u2[4].value) ? 0 : -0;
      break;
    default:
      i2 = Object.is(0, 0 * u2[4].value) ? 0 : -0;
  }
  else if (Number.isFinite(o2[4].value)) switch (n2) {
    case "down":
      i2 = Math.floor(u2[4].value / o2[4].value) * o2[4].value;
      break;
    case "up":
      i2 = Math.ceil(u2[4].value / o2[4].value) * o2[4].value;
      break;
    case "to-zero":
      i2 = Math.trunc(u2[4].value / o2[4].value) * o2[4].value;
      break;
    default: {
      let e3 = Math.floor(u2[4].value / o2[4].value) * o2[4].value, n3 = Math.ceil(u2[4].value / o2[4].value) * o2[4].value;
      if (e3 > n3) {
        const t4 = e3;
        e3 = n3, n3 = t4;
      }
      const t3 = Math.abs(u2[4].value - e3), r3 = Math.abs(u2[4].value - n3);
      i2 = t3 === r3 ? n3 : t3 < r3 ? e3 : n3;
      break;
    }
  }
  else i2 = u2[4].value;
  else i2 = Number.NaN;
  return resultToCalculation(e2, u2, i2);
}
function solveSign(e2, n2, t2) {
  const r2 = n2.value;
  if (!isTokenNumeric(r2)) return -1;
  if (!t2.rawPercentages && isTokenPercentage(r2)) return -1;
  return numberToCalculation(e2, Math.sign(r2[4].value));
}
function solveSin(e2, n2) {
  const t2 = n2.value;
  if (!isDimensionOrNumber(t2)) return -1;
  let r2 = t2[4].value;
  if (isTokenDimension(t2)) switch (toLowerCaseAZ(t2[4].unit)) {
    case "rad":
      break;
    case "deg":
      r2 = P.get("rad")(t2[4].value);
      break;
    case "grad":
      r2 = k.get("rad")(t2[4].value);
      break;
    case "turn":
      r2 = j.get("rad")(t2[4].value);
      break;
    default:
      return -1;
  }
  return r2 = Math.sin(r2), numberToCalculation(e2, r2);
}
function solveSqrt(e2, n2) {
  const t2 = n2.value;
  if (!isTokenNumber(t2)) return -1;
  return numberToCalculation(e2, Math.sqrt(t2[4].value));
}
function solveTan(e2, n2) {
  const t2 = n2.value;
  if (!isDimensionOrNumber(t2)) return -1;
  const r2 = t2[4].value;
  let a2 = 0, u2 = t2[4].value;
  if (isTokenDimension(t2)) switch (toLowerCaseAZ(t2[4].unit)) {
    case "rad":
      a2 = G.get("deg")(r2);
      break;
    case "deg":
      a2 = r2, u2 = P.get("rad")(r2);
      break;
    case "grad":
      a2 = k.get("deg")(r2), u2 = k.get("rad")(r2);
      break;
    case "turn":
      a2 = j.get("deg")(r2), u2 = j.get("rad")(r2);
      break;
    default:
      return -1;
  }
  const o2 = a2 / 90;
  return u2 = a2 % 90 == 0 && o2 % 2 != 0 ? o2 > 0 ? 1 / 0 : -1 / 0 : Math.tan(u2), numberToCalculation(e2, u2);
}
function subtraction(e2, t2) {
  if (2 !== e2.length) return -1;
  const r2 = e2[0].value;
  let a2 = e2[1].value;
  if (isTokenNumber(r2) && isTokenNumber(a2)) {
    const e3 = r2[4].value - a2[4].value;
    return new TokenNode([c.Number, e3.toString(), r2[2], a2[3], { value: e3, type: r2[4].type === a.Integer && a2[4].type === a.Integer ? a.Integer : a.Number }]);
  }
  if (isTokenPercentage(r2) && isTokenPercentage(a2)) {
    const e3 = r2[4].value - a2[4].value;
    return new TokenNode([c.Percentage, e3.toString() + "%", r2[2], a2[3], { value: e3 }]);
  }
  if (isTokenDimension(r2) && isTokenDimension(a2) && (a2 = convertUnit(r2, a2), toLowerCaseAZ(r2[4].unit) === toLowerCaseAZ(a2[4].unit))) {
    const e3 = r2[4].value - a2[4].value;
    return new TokenNode([c.Dimension, e3.toString() + r2[4].unit, r2[2], a2[3], { value: e3, type: r2[4].type === a.Integer && a2[4].type === a.Integer ? a.Integer : a.Number, unit: r2[4].unit }]);
  }
  return (isTokenNumber(r2) && (isTokenDimension(a2) || isTokenPercentage(a2)) || isTokenNumber(a2) && (isTokenDimension(r2) || isTokenPercentage(r2))) && t2.onParseError?.(new ParseErrorWithComponentValues(y.UnexpectedSubtractionOfDimensionOrPercentageWithNumber, e2)), -1;
}
function solveLog(e2, n2) {
  if (1 === n2.length) {
    const r2 = n2[0];
    if (!r2 || !isTokenNode(r2)) return -1;
    const a2 = r2.value;
    if (!isTokenNumber(a2)) return -1;
    return numberToCalculation(e2, Math.log(a2[4].value));
  }
  if (2 === n2.length) {
    const r2 = n2[0];
    if (!r2 || !isTokenNode(r2)) return -1;
    const a2 = r2.value;
    if (!isTokenNumber(a2)) return -1;
    const u2 = n2[1];
    if (!u2 || !isTokenNode(u2)) return -1;
    const o2 = u2.value;
    if (!isTokenNumber(o2)) return -1;
    return numberToCalculation(e2, Math.log(a2[4].value) / Math.log(o2[4].value));
  }
  return -1;
}
var _ = /^none$/i;
function isNone(e2) {
  if (Array.isArray(e2)) {
    const n3 = e2.filter((e3) => !(isWhitespaceNode(e3) && isCommentNode(e3)));
    return 1 === n3.length && isNone(n3[0]);
  }
  if (!isTokenNode(e2)) return false;
  const n2 = e2.value;
  return !!isTokenIdent(n2) && _.test(n2[4].value);
}
var H = String.fromCodePoint(0);
function solveRandom(e2, n2, t2, r2, a2, u2) {
  if (-1 === n2.fixed && !u2.randomCaching) return -1;
  u2.randomCaching || (u2.randomCaching = { propertyName: "", propertyN: 0, elementID: "", documentID: "" }), u2.randomCaching && !u2.randomCaching.propertyN && (u2.randomCaching.propertyN = 0);
  const o2 = t2.value;
  if (!isTokenNumeric(o2)) return -1;
  const i2 = convertUnit(o2, r2.value);
  if (!twoOfSameNumeric(o2, i2)) return -1;
  let l = null;
  if (a2 && (l = convertUnit(o2, a2.value), !twoOfSameNumeric(o2, l))) return -1;
  if (!Number.isFinite(o2[4].value)) return resultToCalculation(e2, o2, Number.NaN);
  if (!Number.isFinite(i2[4].value)) return resultToCalculation(e2, o2, Number.NaN);
  if (!Number.isFinite(i2[4].value - o2[4].value)) return resultToCalculation(e2, o2, Number.NaN);
  if (l && !Number.isFinite(l[4].value)) return resultToCalculation(e2, o2, o2[4].value);
  const c2 = -1 === n2.fixed ? sfc32(crc32([n2.dashedIdent ? n2.dashedIdent : `${u2.randomCaching?.propertyName} ${u2.randomCaching.propertyN++}`, n2.elementShared ? "" : u2.randomCaching.elementID, u2.randomCaching.documentID].join(H))) : () => n2.fixed;
  let s2 = o2[4].value, v = i2[4].value;
  if (s2 > v && ([s2, v] = [v, s2]), l && (l[4].value <= 0 || Math.abs(s2 - v) / l[4].value > 1e10) && (l = null), l) {
    const n3 = Math.max(l[4].value / 1e3, 1e-9), t3 = [s2];
    let r3 = 0;
    for (; ; ) {
      r3 += l[4].value;
      const e3 = s2 + r3;
      if (!(e3 + n3 < v)) {
        t3.push(v);
        break;
      }
      if (t3.push(e3), e3 + l[4].value - n3 > v) break;
    }
    const a3 = c2();
    return resultToCalculation(e2, o2, Number(t3[Math.floor(t3.length * a3)].toFixed(5)));
  }
  const f2 = c2();
  return resultToCalculation(e2, o2, Number((f2 * (v - s2) + s2).toFixed(5)));
}
function sfc32(e2 = 0.34944106645296036, n2 = 0.19228640875738723, t2 = 0.8784393832007205, r2 = 0.04850964319275053) {
  return () => {
    const a2 = ((e2 |= 0) + (n2 |= 0) | 0) + (r2 |= 0) | 0;
    return r2 = r2 + 1 | 0, e2 = n2 ^ n2 >>> 9, n2 = (t2 |= 0) + (t2 << 3) | 0, t2 = (t2 = t2 << 21 | t2 >>> 11) + a2 | 0, (a2 >>> 0) / 4294967296;
  };
}
function crc32(e2) {
  let n2 = 0, t2 = 0, r2 = 0;
  n2 ^= -1;
  for (let a2 = 0, u2 = e2.length; a2 < u2; a2++) r2 = 255 & (n2 ^ e2.charCodeAt(a2)), t2 = Number("0x" + "00000000 77073096 EE0E612C 990951BA 076DC419 706AF48F E963A535 9E6495A3 0EDB8832 79DCB8A4 E0D5E91E 97D2D988 09B64C2B 7EB17CBD E7B82D07 90BF1D91 1DB71064 6AB020F2 F3B97148 84BE41DE 1ADAD47D 6DDDE4EB F4D4B551 83D385C7 136C9856 646BA8C0 FD62F97A 8A65C9EC 14015C4F 63066CD9 FA0F3D63 8D080DF5 3B6E20C8 4C69105E D56041E4 A2677172 3C03E4D1 4B04D447 D20D85FD A50AB56B 35B5A8FA 42B2986C DBBBC9D6 ACBCF940 32D86CE3 45DF5C75 DCD60DCF ABD13D59 26D930AC 51DE003A C8D75180 BFD06116 21B4F4B5 56B3C423 CFBA9599 B8BDA50F 2802B89E 5F058808 C60CD9B2 B10BE924 2F6F7C87 58684C11 C1611DAB B6662D3D 76DC4190 01DB7106 98D220BC EFD5102A 71B18589 06B6B51F 9FBFE4A5 E8B8D433 7807C9A2 0F00F934 9609A88E E10E9818 7F6A0DBB 086D3D2D 91646C97 E6635C01 6B6B51F4 1C6C6162 856530D8 F262004E 6C0695ED 1B01A57B 8208F4C1 F50FC457 65B0D9C6 12B7E950 8BBEB8EA FCB9887C 62DD1DDF 15DA2D49 8CD37CF3 FBD44C65 4DB26158 3AB551CE A3BC0074 D4BB30E2 4ADFA541 3DD895D7 A4D1C46D D3D6F4FB 4369E96A 346ED9FC AD678846 DA60B8D0 44042D73 33031DE5 AA0A4C5F DD0D7CC9 5005713C 270241AA BE0B1010 C90C2086 5768B525 206F85B3 B966D409 CE61E49F 5EDEF90E 29D9C998 B0D09822 C7D7A8B4 59B33D17 2EB40D81 B7BD5C3B C0BA6CAD EDB88320 9ABFB3B6 03B6E20C 74B1D29A EAD54739 9DD277AF 04DB2615 73DC1683 E3630B12 94643B84 0D6D6A3E 7A6A5AA8 E40ECF0B 9309FF9D 0A00AE27 7D079EB1 F00F9344 8708A3D2 1E01F268 6906C2FE F762575D 806567CB 196C3671 6E6B06E7 FED41B76 89D32BE0 10DA7A5A 67DD4ACC F9B9DF6F 8EBEEFF9 17B7BE43 60B08ED5 D6D6A3E8 A1D1937E 38D8C2C4 4FDFF252 D1BB67F1 A6BC5767 3FB506DD 48B2364B D80D2BDA AF0A1B4C 36034AF6 41047A60 DF60EFC3 A867DF55 316E8EEF 4669BE79 CB61B38C BC66831A 256FD2A0 5268E236 CC0C7795 BB0B4703 220216B9 5505262F C5BA3BBE B2BD0B28 2BB45A92 5CB36A04 C2D7FFA7 B5D0CF31 2CD99E8B 5BDEAE1D 9B64C2B0 EC63F226 756AA39C 026D930A 9C0906A9 EB0E363F 72076785 05005713 95BF4A82 E2B87A14 7BB12BAE 0CB61B38 92D28E9B E5D5BE0D 7CDCEFB7 0BDBDF21 86D3D2D4 F1D4E242 68DDB3F8 1FDA836E 81BE16CD F6B9265B 6FB077E1 18B74777 88085AE6 FF0F6A70 66063BCA 11010B5C 8F659EFF F862AE69 616BFFD3 166CCF45 A00AE278 D70DD2EE 4E048354 3903B3C2 A7672661 D06016F7 4969474D 3E6E77DB AED16A4A D9D65ADC 40DF0B66 37D83BF0 A9BCAE53 DEBB9EC5 47B2CF7F 30B5FFE9 BDBDF21C CABAC28A 53B39330 24B4A3A6 BAD03605 CDD70693 54DE5729 23D967BF B3667A2E C4614AB8 5D681B02 2A6F2B94 B40BBE37 C30C8EA1 5A05DF1B 2D02EF8D".substring(9 * r2, 9 * r2 + 8)), n2 = n2 >>> 8 ^ t2;
  return (-1 ^ n2) >>> 0;
}
var J = /* @__PURE__ */ new Map([["abs", function abs(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveAbs);
}], ["acos", function acos(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveACos);
}], ["asin", function asin(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveASin);
}], ["atan", function atan(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveATan);
}], ["atan2", function atan2(e2, n2, t2) {
  return twoCommaSeparatedNodesSolver(e2, n2, t2, solveATan2);
}], ["calc", calc$1], ["clamp", function clamp(r2, a2, o2) {
  const i2 = resolveGlobalsAndConstants([...r2.value.filter((e2) => !isWhiteSpaceOrCommentNode(e2))], a2), c2 = [], s2 = [], v = [];
  {
    let e2 = c2;
    for (let n2 = 0; n2 < i2.length; n2++) {
      const r3 = i2[n2];
      if (isTokenNode(r3) && isTokenComma(r3.value)) {
        if (e2 === v) return -1;
        if (e2 === s2) {
          e2 = v;
          continue;
        }
        if (e2 === c2) {
          e2 = s2;
          continue;
        }
        return -1;
      }
      e2.push(r3);
    }
  }
  const f2 = isNone(c2), p = isNone(v);
  if (f2 && p) return calc$1(calcWrapper(r2, s2), a2, o2);
  const C = solve(calc$1(calcWrapper(r2, s2), a2, o2), o2);
  if (-1 === C) return -1;
  if (f2) {
    const t2 = solve(calc$1(calcWrapper(r2, v), a2, o2), o2);
    return -1 === t2 ? -1 : solveMin((d2 = r2, g = C, D = t2, new FunctionNode([c.Function, "min(", d2.name[2], d2.name[3], { value: "min" }], [c.CloseParen, ")", d2.endToken[2], d2.endToken[3], void 0], [g, new TokenNode([c.Comma, ",", ...sourceIndices(g), void 0]), D])), [C, t2], o2);
  }
  if (p) {
    const e2 = solve(calc$1(calcWrapper(r2, c2), a2, o2), o2);
    return -1 === e2 ? -1 : solveMax(maxWrapper(r2, e2, C), [e2, C], o2);
  }
  var d2, g, D;
  const N = solve(calc$1(calcWrapper(r2, c2), a2, o2), o2);
  if (-1 === N) return -1;
  const h = solve(calc$1(calcWrapper(r2, v), a2, o2), o2);
  if (-1 === h) return -1;
  return solveClamp(r2, N, C, h, o2);
}], ["cos", function cos(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveCos);
}], ["exp", function exp(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveExp);
}], ["hypot", function hypot(e2, n2, t2) {
  return variadicNodesSolver(e2, n2, t2, solveHypot);
}], ["log", function log(e2, n2, t2) {
  return variadicNodesSolver(e2, n2, t2, solveLog);
}], ["max", function max(e2, n2, t2) {
  return variadicNodesSolver(e2, n2, t2, solveMax);
}], ["min", function min(e2, n2, t2) {
  return variadicNodesSolver(e2, n2, t2, solveMin);
}], ["mod", function mod(e2, n2, t2) {
  return twoCommaSeparatedNodesSolver(e2, n2, t2, solveMod);
}], ["pow", function pow(e2, n2, t2) {
  return twoCommaSeparatedNodesSolver(e2, n2, t2, solvePow);
}], ["random", function random(e2, n2, t2) {
  const r2 = parseRandomValueSharing(e2, e2.value.filter((e3) => !isWhiteSpaceOrCommentNode(e3)), n2, t2);
  if (-1 === r2) return -1;
  const [a2, o2] = r2, i2 = variadicArguments(e2, o2, n2, t2);
  if (-1 === i2) return -1;
  const [l, c2, s2] = i2;
  if (!l || !c2) return -1;
  return solveRandom(e2, a2, l, c2, s2, t2);
}], ["rem", function rem(e2, n2, t2) {
  return twoCommaSeparatedNodesSolver(e2, n2, t2, solveRem);
}], ["round", function round(e2, r2, a2) {
  const o2 = resolveGlobalsAndConstants([...e2.value.filter((e3) => !isWhiteSpaceOrCommentNode(e3))], r2);
  let i2 = "", l = false;
  const c2 = [], s2 = [];
  {
    let e3 = c2;
    for (let n2 = 0; n2 < o2.length; n2++) {
      const r3 = o2[n2];
      if (!i2 && 0 === c2.length && 0 === s2.length && isTokenNode(r3) && isTokenIdent(r3.value)) {
        const e4 = r3.value[4].value.toLowerCase();
        if (K.has(e4)) {
          i2 = e4;
          continue;
        }
      }
      if (isTokenNode(r3) && isTokenComma(r3.value)) {
        if (e3 === s2) return -1;
        if (e3 === c2 && i2 && 0 === c2.length) continue;
        if (e3 === c2) {
          l = true, e3 = s2;
          continue;
        }
        return -1;
      }
      e3.push(r3);
    }
  }
  const v = solve(calc$1(calcWrapper(e2, c2), r2, a2), a2);
  if (-1 === v) return -1;
  l || 0 !== s2.length || s2.push(new TokenNode([c.Number, "1", v.value[2], v.value[3], { value: 1, type: a.Integer }]));
  const f2 = solve(calc$1(calcWrapper(e2, s2), r2, a2), a2);
  if (-1 === f2) return -1;
  i2 || (i2 = "nearest");
  return solveRound(e2, i2, v, f2, a2);
}], ["sign", function sign(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveSign);
}], ["sin", function sin(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveSin);
}], ["sqrt", function sqrt(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveSqrt);
}], ["tan", function tan(e2, n2, t2) {
  return singleNodeSolver(e2, n2, t2, solveTan);
}]]);
function calc$1(e2, n2, r2) {
  const a2 = resolveGlobalsAndConstants([...e2.value.filter((e3) => !isWhiteSpaceOrCommentNode(e3))], n2);
  if (1 === a2.length && isTokenNode(a2[0])) return { inputs: [a2[0]], operation: unary };
  let l = 0;
  for (; l < a2.length; ) {
    const e3 = a2[l];
    if (isSimpleBlockNode(e3) && isTokenOpenParen(e3.startToken)) {
      const t2 = calc$1(e3, n2, r2);
      if (-1 === t2) return -1;
      a2.splice(l, 1, t2);
      continue;
    }
    if (isFunctionNode(e3)) {
      const t2 = J.get(e3.getName().toLowerCase());
      if (!t2) return -1;
      const u2 = t2(e3, n2, r2);
      if (-1 === u2) return -1;
      a2.splice(l, 1, u2);
      continue;
    }
    l++;
  }
  if (l = 0, 1 === a2.length && isCalculation(a2[0])) return a2[0];
  for (; l < a2.length; ) {
    const e3 = a2[l];
    if (!e3 || !isTokenNode(e3) && !isCalculation(e3)) {
      l++;
      continue;
    }
    const n3 = a2[l + 1];
    if (!n3 || !isTokenNode(n3)) {
      l++;
      continue;
    }
    const r3 = n3.value;
    if (!isTokenDelim(r3) || "*" !== r3[4].value && "/" !== r3[4].value) {
      l++;
      continue;
    }
    const u2 = a2[l + 2];
    if (!u2 || !isTokenNode(u2) && !isCalculation(u2)) return -1;
    "*" !== r3[4].value ? "/" !== r3[4].value ? l++ : a2.splice(l, 3, { inputs: [e3, u2], operation: division }) : a2.splice(l, 3, { inputs: [e3, u2], operation: multiplication });
  }
  if (l = 0, 1 === a2.length && isCalculation(a2[0])) return a2[0];
  for (; l < a2.length; ) {
    const e3 = a2[l];
    if (!e3 || !isTokenNode(e3) && !isCalculation(e3)) {
      l++;
      continue;
    }
    const n3 = a2[l + 1];
    if (!n3 || !isTokenNode(n3)) {
      l++;
      continue;
    }
    const r3 = n3.value;
    if (!isTokenDelim(r3) || "+" !== r3[4].value && "-" !== r3[4].value) {
      l++;
      continue;
    }
    const u2 = a2[l + 2];
    if (!u2 || !isTokenNode(u2) && !isCalculation(u2)) return -1;
    "+" !== r3[4].value ? "-" !== r3[4].value ? l++ : a2.splice(l, 3, { inputs: [e3, u2], operation: subtraction }) : a2.splice(l, 3, { inputs: [e3, u2], operation: addition });
  }
  return 1 === a2.length && isCalculation(a2[0]) ? a2[0] : -1;
}
function singleNodeSolver(e2, n2, t2, r2) {
  const a2 = singleArgument(e2, n2, t2);
  return -1 === a2 ? -1 : r2(e2, a2, t2);
}
function singleArgument(e2, n2, t2) {
  const r2 = resolveGlobalsAndConstants([...e2.value.filter((e3) => !isWhiteSpaceOrCommentNode(e3))], n2), a2 = solve(calc$1(calcWrapper(e2, r2), n2, t2), t2);
  return -1 === a2 ? -1 : a2;
}
function twoCommaSeparatedNodesSolver(e2, n2, t2, r2) {
  const a2 = twoCommaSeparatedArguments(e2, n2, t2);
  if (-1 === a2) return -1;
  const [u2, o2] = a2;
  return r2(e2, u2, o2, t2);
}
function twoCommaSeparatedArguments(e2, n2, r2) {
  const a2 = resolveGlobalsAndConstants([...e2.value.filter((e3) => !isWhiteSpaceOrCommentNode(e3))], n2), o2 = [], i2 = [];
  {
    let e3 = o2;
    for (let n3 = 0; n3 < a2.length; n3++) {
      const r3 = a2[n3];
      if (isTokenNode(r3) && isTokenComma(r3.value)) {
        if (e3 === i2) return -1;
        if (e3 === o2) {
          e3 = i2;
          continue;
        }
        return -1;
      }
      e3.push(r3);
    }
  }
  const l = solve(calc$1(calcWrapper(e2, o2), n2, r2), r2);
  if (-1 === l) return -1;
  const c2 = solve(calc$1(calcWrapper(e2, i2), n2, r2), r2);
  return -1 === c2 ? -1 : [l, c2];
}
function variadicNodesSolver(e2, n2, t2, r2) {
  const a2 = variadicArguments(e2, e2.value, n2, t2);
  return -1 === a2 ? -1 : r2(e2, a2, t2);
}
function variadicArguments(e2, n2, r2, a2) {
  const o2 = resolveGlobalsAndConstants([...n2.filter((e3) => !isWhiteSpaceOrCommentNode(e3))], r2), i2 = [];
  {
    const n3 = [];
    let u2 = [];
    for (let e3 = 0; e3 < o2.length; e3++) {
      const r3 = o2[e3];
      isTokenNode(r3) && isTokenComma(r3.value) ? (n3.push(u2), u2 = []) : u2.push(r3);
    }
    n3.push(u2);
    for (let t2 = 0; t2 < n3.length; t2++) {
      if (0 === n3[t2].length) return -1;
      const u3 = solve(calc$1(calcWrapper(e2, n3[t2]), r2, a2), a2);
      if (-1 === u3) return -1;
      i2.push(u3);
    }
  }
  return i2;
}
var K = /* @__PURE__ */ new Set(["nearest", "up", "down", "to-zero"]);
function parseRandomValueSharing(e2, n2, r2, a2) {
  const u2 = { isAuto: false, dashedIdent: "", fixed: -1, elementShared: false }, o2 = n2[0];
  if (!isTokenNode(o2) || !isTokenIdent(o2.value)) return [u2, n2];
  for (let o3 = 0; o3 < n2.length; o3++) {
    const i2 = n2[o3];
    if (!isTokenNode(i2)) return -1;
    if (isTokenComma(i2.value)) return [u2, n2.slice(o3 + 1)];
    if (!isTokenIdent(i2.value)) return -1;
    const l = i2.value[4].value.toLowerCase();
    if ("element-shared" !== l) {
      if ("fixed" === l) {
        if (u2.elementShared || u2.dashedIdent || u2.isAuto) return -1;
        o3++;
        const t2 = n2[o3];
        if (!t2) return -1;
        const i3 = solve(calc$1(calcWrapper(e2, [t2]), r2, a2), a2);
        if (-1 === i3) return -1;
        if (!isTokenNumber(i3.value)) return -1;
        if (i3.value[4].value < 0 || i3.value[4].value > 1) return -1;
        u2.fixed = Math.max(0, Math.min(i3.value[4].value, 1 - 1e-9));
        continue;
      }
      if ("auto" !== l) if (l.startsWith("--")) {
        if (-1 !== u2.fixed || u2.isAuto) return -1;
        u2.dashedIdent = l;
      } else ;
      else {
        if (-1 !== u2.fixed || u2.dashedIdent) return -1;
        u2.isAuto = true;
      }
    } else {
      if (-1 !== u2.fixed) return -1;
      u2.elementShared = true;
    }
  }
  return -1;
}
function calcWrapper(e2, n2) {
  return new FunctionNode([c.Function, "calc(", e2.name[2], e2.name[3], { value: "calc" }], [c.CloseParen, ")", e2.endToken[2], e2.endToken[3], void 0], n2);
}
function maxWrapper(t2, r2, a2) {
  return new FunctionNode([c.Function, "max(", t2.name[2], t2.name[3], { value: "max" }], [c.CloseParen, ")", t2.endToken[2], t2.endToken[3], void 0], [r2, new TokenNode([c.Comma, ",", ...sourceIndices(r2), void 0]), a2]);
}
function patchNaN(e2) {
  if (-1 === e2) return -1;
  if (isFunctionNode(e2)) return e2;
  const t2 = e2.value;
  return isTokenNumeric(t2) && Number.isNaN(t2[4].value) ? isTokenNumber(t2) ? new FunctionNode([c.Function, "calc(", t2[2], t2[3], { value: "calc" }], [c.CloseParen, ")", t2[2], t2[3], void 0], [new TokenNode([c.Ident, "NaN", t2[2], t2[3], { value: "NaN" }])]) : isTokenDimension(t2) ? new FunctionNode([c.Function, "calc(", t2[2], t2[3], { value: "calc" }], [c.CloseParen, ")", t2[2], t2[3], void 0], [new TokenNode([c.Ident, "NaN", t2[2], t2[3], { value: "NaN" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Delim, "*", t2[2], t2[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Dimension, "1" + t2[4].unit, t2[2], t2[3], { value: 1, type: a.Integer, unit: t2[4].unit }])]) : isTokenPercentage(t2) ? new FunctionNode([c.Function, "calc(", t2[2], t2[3], { value: "calc" }], [c.CloseParen, ")", t2[2], t2[3], void 0], [new TokenNode([c.Ident, "NaN", t2[2], t2[3], { value: "NaN" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Delim, "*", t2[2], t2[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Percentage, "1%", t2[2], t2[3], { value: 1 }])]) : -1 : e2;
}
function patchInfinity(e2) {
  if (-1 === e2) return -1;
  if (isFunctionNode(e2)) return e2;
  const t2 = e2.value;
  if (!isTokenNumeric(t2)) return e2;
  if (Number.isFinite(t2[4].value) || Number.isNaN(t2[4].value)) return e2;
  let r2 = "";
  return Number.NEGATIVE_INFINITY === t2[4].value && (r2 = "-"), isTokenNumber(t2) ? new FunctionNode([c.Function, "calc(", t2[2], t2[3], { value: "calc" }], [c.CloseParen, ")", t2[2], t2[3], void 0], [new TokenNode([c.Ident, r2 + "infinity", t2[2], t2[3], { value: r2 + "infinity" }])]) : isTokenDimension(t2) ? new FunctionNode([c.Function, "calc(", t2[2], t2[3], { value: "calc" }], [c.CloseParen, ")", t2[2], t2[3], void 0], [new TokenNode([c.Ident, r2 + "infinity", t2[2], t2[3], { value: r2 + "infinity" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Delim, "*", t2[2], t2[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Dimension, "1" + t2[4].unit, t2[2], t2[3], { value: 1, type: a.Integer, unit: t2[4].unit }])]) : new FunctionNode([c.Function, "calc(", t2[2], t2[3], { value: "calc" }], [c.CloseParen, ")", t2[2], t2[3], void 0], [new TokenNode([c.Ident, r2 + "infinity", t2[2], t2[3], { value: r2 + "infinity" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Delim, "*", t2[2], t2[3], { value: "*" }]), new WhitespaceNode([[c.Whitespace, " ", t2[2], t2[3], void 0]]), new TokenNode([c.Percentage, "1%", t2[2], t2[3], { value: 1 }])]);
}
function patchMinusZero(e2) {
  if (-1 === e2) return -1;
  if (isFunctionNode(e2)) return e2;
  const n2 = e2.value;
  return isTokenNumeric(n2) && Object.is(-0, n2[4].value) ? ("-0" === n2[1] || (isTokenPercentage(n2) ? n2[1] = "-0%" : isTokenDimension(n2) ? n2[1] = "-0" + n2[4].unit : n2[1] = "-0"), e2) : e2;
}
function patchPrecision(e2, n2 = 13) {
  if (-1 === e2) return -1;
  if (n2 <= 0) return e2;
  if (isFunctionNode(e2)) return e2;
  const t2 = e2.value;
  if (!isTokenNumeric(t2)) return e2;
  if (Number.isInteger(t2[4].value)) return e2;
  const r2 = Number(t2[4].value.toFixed(n2)).toString();
  return isTokenNumber(t2) ? t2[1] = r2 : isTokenPercentage(t2) ? t2[1] = r2 + "%" : isTokenDimension(t2) && (t2[1] = r2 + t2[4].unit), e2;
}
function patchCanonicalUnit(e2) {
  return -1 === e2 ? -1 : isFunctionNode(e2) ? e2 : isTokenDimension(e2.value) ? (e2.value = toCanonicalUnit(e2.value), e2) : e2;
}
function patchCalcResult(e2, n2) {
  let t2 = e2;
  return n2?.toCanonicalUnits && (t2 = patchCanonicalUnit(t2)), t2 = patchPrecision(t2, n2?.precision), t2 = patchMinusZero(t2), n2?.censorIntoStandardRepresentableValues || (t2 = patchNaN(t2), t2 = patchInfinity(t2)), t2;
}
function tokenizeGlobals(e2) {
  const n2 = /* @__PURE__ */ new Map();
  if (!e2) return n2;
  for (const [t2, r2] of e2) if (isToken(r2)) n2.set(t2, r2);
  else if ("string" == typeof r2) {
    const e3 = tokenizer({ css: r2 }), a2 = e3.nextToken();
    if (e3.nextToken(), !e3.endOfFile()) continue;
    if (!isTokenNumeric(a2)) continue;
    n2.set(t2, a2);
    continue;
  }
  return n2;
}
function calc(e2, n2) {
  return calcFromComponentValues(parseCommaSeparatedListOfComponentValues(tokenize({ css: e2 }), {}), n2).map((e3) => e3.map((e4) => stringify(...e4.tokens())).join("")).join(",");
}
function calcFromComponentValues(e2, n2) {
  const t2 = tokenizeGlobals(n2?.globals);
  return replaceComponentValues2(e2, (e3) => {
    if (!isFunctionNode(e3)) return;
    const r2 = J.get(e3.getName().toLowerCase());
    if (!r2) return;
    const a2 = patchCalcResult(solve(r2(e3, t2, n2 ?? {}), n2 ?? {}), n2);
    return -1 !== a2 ? a2 : void 0;
  });
}
function replaceComponentValues2(n2, r2) {
  for (let a2 = 0; a2 < n2.length; a2++) {
    const o2 = n2[a2];
    walk(o2, (n3, a3) => {
      if ("number" != typeof a3) return;
      const o3 = r2(n3.node);
      if (!o3) return;
      const i2 = [o3], l = n3.parent.value[a3 - 1];
      isTokenNode(l) && isTokenDelim(l.value) && ("-" === l.value[4].value || "+" === l.value[4].value) && i2.splice(0, 0, new WhitespaceNode([[c.Whitespace, " ", ...sourceIndices(n3.node), void 0]]));
      const s2 = n3.parent.value[a3 + 1];
      !s2 || isWhiteSpaceOrCommentNode(s2) || isTokenNode(s2) && (isTokenComma(s2.value) || isTokenColon(s2.value) || isTokenSemicolon(s2.value) || isTokenDelim(s2.value) && "-" !== s2.value[4].value && "+" !== s2.value[4].value) || i2.push(new WhitespaceNode([[c.Whitespace, " ", ...sourceIndices(n3.node), void 0]])), n3.parent.value.splice(a3, 1, ...i2);
    });
  }
  return n2;
}
var Q = new Set(J.keys());
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  ParseError,
  ParseErrorMessage,
  ParseErrorWithComponentValues,
  calc,
  calcFromComponentValues,
  mathFunctionNames
});
