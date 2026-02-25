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
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// node_modules/@csstools/css-tokenizer/dist/index.mjs
var dist_exports = {};
__export(dist_exports, {
  HashType: () => u,
  NumberType: () => a,
  ParseError: () => ParseError,
  ParseErrorMessage: () => e,
  ParseErrorWithToken: () => ParseErrorWithToken,
  TokenType: () => c,
  cloneTokens: () => cloneTokens,
  isToken: () => isToken,
  isTokenAtKeyword: () => isTokenAtKeyword,
  isTokenBadString: () => isTokenBadString,
  isTokenBadURL: () => isTokenBadURL,
  isTokenCDC: () => isTokenCDC,
  isTokenCDO: () => isTokenCDO,
  isTokenCloseCurly: () => isTokenCloseCurly,
  isTokenCloseParen: () => isTokenCloseParen,
  isTokenCloseSquare: () => isTokenCloseSquare,
  isTokenColon: () => isTokenColon,
  isTokenComma: () => isTokenComma,
  isTokenComment: () => isTokenComment,
  isTokenDelim: () => isTokenDelim,
  isTokenDimension: () => isTokenDimension,
  isTokenEOF: () => isTokenEOF,
  isTokenFunction: () => isTokenFunction,
  isTokenHash: () => isTokenHash,
  isTokenIdent: () => isTokenIdent,
  isTokenNumber: () => isTokenNumber,
  isTokenNumeric: () => isTokenNumeric,
  isTokenOpenCurly: () => isTokenOpenCurly,
  isTokenOpenParen: () => isTokenOpenParen,
  isTokenOpenSquare: () => isTokenOpenSquare,
  isTokenPercentage: () => isTokenPercentage,
  isTokenSemicolon: () => isTokenSemicolon,
  isTokenString: () => isTokenString,
  isTokenURL: () => isTokenURL,
  isTokenUnicodeRange: () => isTokenUnicodeRange,
  isTokenWhiteSpaceOrComment: () => isTokenWhiteSpaceOrComment,
  isTokenWhitespace: () => isTokenWhitespace,
  mirrorVariant: () => mirrorVariant,
  mirrorVariantType: () => mirrorVariantType,
  mutateIdent: () => mutateIdent,
  mutateUnit: () => mutateUnit,
  stringify: () => stringify,
  tokenize: () => tokenize,
  tokenizer: () => tokenizer
});
module.exports = __toCommonJS(dist_exports);
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
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  HashType,
  NumberType,
  ParseError,
  ParseErrorMessage,
  ParseErrorWithToken,
  TokenType,
  cloneTokens,
  isToken,
  isTokenAtKeyword,
  isTokenBadString,
  isTokenBadURL,
  isTokenCDC,
  isTokenCDO,
  isTokenCloseCurly,
  isTokenCloseParen,
  isTokenCloseSquare,
  isTokenColon,
  isTokenComma,
  isTokenComment,
  isTokenDelim,
  isTokenDimension,
  isTokenEOF,
  isTokenFunction,
  isTokenHash,
  isTokenIdent,
  isTokenNumber,
  isTokenNumeric,
  isTokenOpenCurly,
  isTokenOpenParen,
  isTokenOpenSquare,
  isTokenPercentage,
  isTokenSemicolon,
  isTokenString,
  isTokenURL,
  isTokenUnicodeRange,
  isTokenWhiteSpaceOrComment,
  isTokenWhitespace,
  mirrorVariant,
  mirrorVariantType,
  mutateIdent,
  mutateUnit,
  stringify,
  tokenize,
  tokenizer
});
