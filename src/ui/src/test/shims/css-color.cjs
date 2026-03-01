"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __commonJS = (cb, mod2) => function __require() {
  return mod2 || (0, cb[__getOwnPropNames(cb)[0]])((mod2 = { exports: {} }).exports, mod2), mod2.exports;
};
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
function cloneTokens(e3) {
  return n ? structuredClone(e3) : JSON.parse(JSON.stringify(e3));
}
function stringify(...e3) {
  let n3 = "";
  for (let t3 = 0; t3 < e3.length; t3++) n3 += e3[t3][1];
  return n3;
}
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
  const a3 = n3.css.valueOf(), u3 = n3.unicodeRangesAllowed ?? false, d3 = new Reader(a3), p = { onParseError: s3?.onParseError ?? noop };
  return { nextToken: function nextToken() {
    d3.resetRepresentation();
    const n4 = d3.source.codePointAt(d3.cursor);
    if (void 0 === n4) return [c.EOF, "", -1, -1, void 0];
    if (47 === n4 && checkIfTwoCodePointsStartAComment(d3)) return consumeComment(p, d3);
    if (u3 && (117 === n4 || 85 === n4) && checkIfThreeCodePointsWouldStartAUnicodeRange(d3)) return consumeUnicodeRangeToken(0, d3);
    if (isIdentStartCodePoint(n4)) return consumeIdentLikeToken(p, d3);
    if (isDigitCodePoint(n4)) return consumeNumericToken(p, d3);
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
        return consumeStringToken(p, d3);
      case 35:
        return consumeHashToken(p, d3);
      case i:
      case 46:
        return checkIfThreeCodePointsWouldStartANumber(d3) ? consumeNumericToken(p, d3) : (d3.advanceCodePoint(), [c.Delim, d3.source[d3.representationStart], d3.representationStart, d3.representationEnd, { value: d3.source[d3.representationStart] }]);
      case r:
      case t:
      case 12:
      case 9:
      case 32:
        return consumeWhiteSpace(d3);
      case o:
        return checkIfThreeCodePointsWouldStartANumber(d3) ? consumeNumericToken(p, d3) : checkIfThreeCodePointsWouldStartCDC(d3) ? (d3.advanceCodePoint(3), [c.CDC, "-->", d3.representationStart, d3.representationEnd, void 0]) : checkIfThreeCodePointsWouldStartAnIdentSequence(0, d3) ? consumeIdentLikeToken(p, d3) : (d3.advanceCodePoint(), [c.Delim, "-", d3.representationStart, d3.representationEnd, { value: "-" }]);
      case 60:
        return checkIfFourCodePointsWouldStartCDO(d3) ? (d3.advanceCodePoint(4), [c.CDO, "<!--", d3.representationStart, d3.representationEnd, void 0]) : (d3.advanceCodePoint(), [c.Delim, "<", d3.representationStart, d3.representationEnd, { value: "<" }]);
      case 64:
        if (d3.advanceCodePoint(), checkIfThreeCodePointsWouldStartAnIdentSequence(0, d3)) {
          const e3 = consumeIdentSequence(p, d3);
          return [c.AtKeyword, d3.source.slice(d3.representationStart, d3.representationEnd + 1), d3.representationStart, d3.representationEnd, { value: String.fromCodePoint(...e3) }];
        }
        return [c.Delim, "@", d3.representationStart, d3.representationEnd, { value: "@" }];
      case 92: {
        if (checkIfTwoCodePointsAreAValidEscape(d3)) return consumeIdentLikeToken(p, d3);
        d3.advanceCodePoint();
        const n5 = [c.Delim, "\\", d3.representationStart, d3.representationEnd, { value: "\\" }];
        return p.onParseError(new ParseErrorWithToken(e.InvalidEscapeSequenceAfterBackslash, d3.representationStart, d3.representationEnd, ["4.3.1. Consume a token", "U+005C REVERSE SOLIDUS (\\)", "The input stream does not start with a valid escape sequence"], n5)), n5;
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
var ParseError, ParseErrorWithToken, e, n, t, o, r, i, s, c, a, u, Reader, d;
var init_dist = __esm({
  "node_modules/@csstools/css-tokenizer/dist/index.mjs"() {
    ParseError = class extends Error {
      sourceStart;
      sourceEnd;
      parserState;
      constructor(e3, n3, t3, o3) {
        super(e3), this.name = "ParseError", this.sourceStart = n3, this.sourceEnd = t3, this.parserState = o3;
      }
    };
    ParseErrorWithToken = class extends ParseError {
      token;
      constructor(e3, n3, t3, o3, r3) {
        super(e3, n3, t3, o3), this.token = r3;
      }
    };
    e = { UnexpectedNewLineInString: "Unexpected newline while consuming a string token.", UnexpectedEOFInString: "Unexpected EOF while consuming a string token.", UnexpectedEOFInComment: "Unexpected EOF while consuming a comment.", UnexpectedEOFInURL: "Unexpected EOF while consuming a url token.", UnexpectedEOFInEscapedCodePoint: "Unexpected EOF while consuming an escaped code point.", UnexpectedCharacterInURL: "Unexpected character while consuming a url token.", InvalidEscapeSequenceInURL: "Invalid escape sequence while consuming a url token.", InvalidEscapeSequenceAfterBackslash: 'Invalid escape sequence after "\\"' };
    n = "undefined" != typeof globalThis && "structuredClone" in globalThis;
    t = 13;
    o = 45;
    r = 10;
    i = 43;
    s = 65533;
    !function(e3) {
      e3.Comment = "comment", e3.AtKeyword = "at-keyword-token", e3.BadString = "bad-string-token", e3.BadURL = "bad-url-token", e3.CDC = "CDC-token", e3.CDO = "CDO-token", e3.Colon = "colon-token", e3.Comma = "comma-token", e3.Delim = "delim-token", e3.Dimension = "dimension-token", e3.EOF = "EOF-token", e3.Function = "function-token", e3.Hash = "hash-token", e3.Ident = "ident-token", e3.Number = "number-token", e3.Percentage = "percentage-token", e3.Semicolon = "semicolon-token", e3.String = "string-token", e3.URL = "url-token", e3.Whitespace = "whitespace-token", e3.OpenParen = "(-token", e3.CloseParen = ")-token", e3.OpenSquare = "[-token", e3.CloseSquare = "]-token", e3.OpenCurly = "{-token", e3.CloseCurly = "}-token", e3.UnicodeRange = "unicode-range-token";
    }(c || (c = {})), function(e3) {
      e3.Integer = "integer", e3.Number = "number";
    }(a || (a = {})), function(e3) {
      e3.Unrestricted = "unrestricted", e3.ID = "id";
    }(u || (u = {}));
    Reader = class {
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
    d = Object.values(c);
  }
});

// node_modules/@csstools/css-parser-algorithms/dist/index.mjs
var dist_exports2 = {};
__export(dist_exports2, {
  CommentNode: () => CommentNode,
  ComponentValueType: () => f,
  ContainerNodeBaseClass: () => ContainerNodeBaseClass,
  FunctionNode: () => FunctionNode,
  SimpleBlockNode: () => SimpleBlockNode,
  TokenNode: () => TokenNode,
  WhitespaceNode: () => WhitespaceNode,
  forEach: () => forEach,
  gatherNodeAncestry: () => gatherNodeAncestry,
  isCommentNode: () => isCommentNode,
  isFunctionNode: () => isFunctionNode,
  isSimpleBlockNode: () => isSimpleBlockNode,
  isTokenNode: () => isTokenNode,
  isWhiteSpaceOrCommentNode: () => isWhiteSpaceOrCommentNode,
  isWhitespaceNode: () => isWhitespaceNode,
  parseCommaSeparatedListOfComponentValues: () => parseCommaSeparatedListOfComponentValues,
  parseComponentValue: () => parseComponentValue,
  parseListOfComponentValues: () => parseListOfComponentValues,
  replaceComponentValues: () => replaceComponentValues,
  sourceIndices: () => sourceIndices,
  stringify: () => stringify2,
  walk: () => walk,
  walkerIndexGenerator: () => walkerIndexGenerator
});
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
function consumeWhitespace(e3, n3) {
  let t3 = 0;
  for (; ; ) {
    const e4 = n3[t3];
    if (!isTokenWhitespace(e4)) return { advance: t3, node: new WhitespaceNode(n3.slice(0, t3)) };
    t3++;
  }
}
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
var f, ContainerNodeBaseClass, FunctionNode, SimpleBlockNode, WhitespaceNode, CommentNode, TokenNode;
var init_dist2 = __esm({
  "node_modules/@csstools/css-parser-algorithms/dist/index.mjs"() {
    init_dist();
    !function(e3) {
      e3.Function = "function", e3.SimpleBlock = "simple-block", e3.Whitespace = "whitespace", e3.Comment = "comment", e3.Token = "token";
    }(f || (f = {}));
    ContainerNodeBaseClass = class {
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
    FunctionNode = class _FunctionNode extends ContainerNodeBaseClass {
      type = f.Function;
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
        return !!e3 && (e3 instanceof _FunctionNode && e3.type === f.Function);
      }
    };
    SimpleBlockNode = class _SimpleBlockNode extends ContainerNodeBaseClass {
      type = f.SimpleBlock;
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
        return !!e3 && (e3 instanceof _SimpleBlockNode && e3.type === f.SimpleBlock);
      }
    };
    WhitespaceNode = class _WhitespaceNode {
      type = f.Whitespace;
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
        return !!e3 && (e3 instanceof _WhitespaceNode && e3.type === f.Whitespace);
      }
    };
    CommentNode = class _CommentNode {
      type = f.Comment;
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
        return !!e3 && (e3 instanceof _CommentNode && e3.type === f.Comment);
      }
    };
    TokenNode = class _TokenNode {
      type = f.Token;
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
        return !!e3 && (e3 instanceof _TokenNode && e3.type === f.Token);
      }
    };
  }
});

// node_modules/@csstools/css-calc/dist/index.mjs
var dist_exports3 = {};
__export(dist_exports3, {
  ParseError: () => ParseError2,
  ParseErrorMessage: () => y,
  ParseErrorWithComponentValues: () => ParseErrorWithComponentValues,
  calc: () => calc,
  calcFromComponentValues: () => calcFromComponentValues,
  mathFunctionNames: () => Q
});
function toLowerCaseAZ(e3) {
  return e3.replace(M, (e4) => String.fromCharCode(e4.charCodeAt(0) + 32));
}
function convertUnit(e3, n3) {
  if (!isTokenDimension(e3)) return n3;
  if (!isTokenDimension(n3)) return n3;
  const t3 = toLowerCaseAZ(e3[4].unit), r3 = toLowerCaseAZ(n3[4].unit);
  if (t3 === r3) return n3;
  const a3 = Y.get(r3);
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
  const r3 = Y.get(n3);
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
function isNone(e3) {
  if (Array.isArray(e3)) {
    const n4 = e3.filter((e4) => !(isWhitespaceNode(e4) && isCommentNode(e4)));
    return 1 === n4.length && isNone(n4[0]);
  }
  if (!isTokenNode(e3)) return false;
  const n3 = e3.value;
  return !!isTokenIdent(n3) && _.test(n3[4].value);
}
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
var ParseError2, ParseErrorWithComponentValues, y, M, T, x, P, k, O, W, U, L, V, $, Z, z, q, G, R, j, Y, _, H, J, K, Q;
var init_dist3 = __esm({
  "node_modules/@csstools/css-calc/dist/index.mjs"() {
    init_dist2();
    init_dist();
    ParseError2 = class extends Error {
      sourceStart;
      sourceEnd;
      constructor(e3, n3, t3) {
        super(e3), this.name = "ParseError", this.sourceStart = n3, this.sourceEnd = t3;
      }
    };
    ParseErrorWithComponentValues = class extends ParseError2 {
      componentValues;
      constructor(n3, t3) {
        super(n3, ...sourceIndices(t3)), this.componentValues = t3;
      }
    };
    y = { UnexpectedAdditionOfDimensionOrPercentageWithNumber: "Unexpected addition of a dimension or percentage with a number.", UnexpectedSubtractionOfDimensionOrPercentageWithNumber: "Unexpected subtraction of a dimension or percentage with a number." };
    M = /[A-Z]/g;
    T = { cm: "px", in: "px", mm: "px", pc: "px", pt: "px", px: "px", q: "px", deg: "deg", grad: "deg", rad: "deg", turn: "deg", ms: "s", s: "s", hz: "hz", khz: "hz" };
    x = /* @__PURE__ */ new Map([["cm", (e3) => e3], ["mm", (e3) => 10 * e3], ["q", (e3) => 40 * e3], ["in", (e3) => e3 / 2.54], ["pc", (e3) => e3 / 2.54 * 6], ["pt", (e3) => e3 / 2.54 * 72], ["px", (e3) => e3 / 2.54 * 96]]);
    P = /* @__PURE__ */ new Map([["deg", (e3) => e3], ["grad", (e3) => e3 / 0.9], ["rad", (e3) => e3 / 180 * Math.PI], ["turn", (e3) => e3 / 360]]);
    k = /* @__PURE__ */ new Map([["deg", (e3) => 0.9 * e3], ["grad", (e3) => e3], ["rad", (e3) => 0.9 * e3 / 180 * Math.PI], ["turn", (e3) => 0.9 * e3 / 360]]);
    O = /* @__PURE__ */ new Map([["hz", (e3) => e3], ["khz", (e3) => e3 / 1e3]]);
    W = /* @__PURE__ */ new Map([["cm", (e3) => 2.54 * e3], ["mm", (e3) => 25.4 * e3], ["q", (e3) => 25.4 * e3 * 4], ["in", (e3) => e3], ["pc", (e3) => 6 * e3], ["pt", (e3) => 72 * e3], ["px", (e3) => 96 * e3]]);
    U = /* @__PURE__ */ new Map([["hz", (e3) => 1e3 * e3], ["khz", (e3) => e3]]);
    L = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 10], ["mm", (e3) => e3], ["q", (e3) => 4 * e3], ["in", (e3) => e3 / 25.4], ["pc", (e3) => e3 / 25.4 * 6], ["pt", (e3) => e3 / 25.4 * 72], ["px", (e3) => e3 / 25.4 * 96]]);
    V = /* @__PURE__ */ new Map([["ms", (e3) => e3], ["s", (e3) => e3 / 1e3]]);
    $ = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 6 * 2.54], ["mm", (e3) => e3 / 6 * 25.4], ["q", (e3) => e3 / 6 * 25.4 * 4], ["in", (e3) => e3 / 6], ["pc", (e3) => e3], ["pt", (e3) => e3 / 6 * 72], ["px", (e3) => e3 / 6 * 96]]);
    Z = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 72 * 2.54], ["mm", (e3) => e3 / 72 * 25.4], ["q", (e3) => e3 / 72 * 25.4 * 4], ["in", (e3) => e3 / 72], ["pc", (e3) => e3 / 72 * 6], ["pt", (e3) => e3], ["px", (e3) => e3 / 72 * 96]]);
    z = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 96 * 2.54], ["mm", (e3) => e3 / 96 * 25.4], ["q", (e3) => e3 / 96 * 25.4 * 4], ["in", (e3) => e3 / 96], ["pc", (e3) => e3 / 96 * 6], ["pt", (e3) => e3 / 96 * 72], ["px", (e3) => e3]]);
    q = /* @__PURE__ */ new Map([["cm", (e3) => e3 / 4 / 10], ["mm", (e3) => e3 / 4], ["q", (e3) => e3], ["in", (e3) => e3 / 4 / 25.4], ["pc", (e3) => e3 / 4 / 25.4 * 6], ["pt", (e3) => e3 / 4 / 25.4 * 72], ["px", (e3) => e3 / 4 / 25.4 * 96]]);
    G = /* @__PURE__ */ new Map([["deg", (e3) => 180 * e3 / Math.PI], ["grad", (e3) => 180 * e3 / Math.PI / 0.9], ["rad", (e3) => e3], ["turn", (e3) => 180 * e3 / Math.PI / 360]]);
    R = /* @__PURE__ */ new Map([["ms", (e3) => 1e3 * e3], ["s", (e3) => e3]]);
    j = /* @__PURE__ */ new Map([["deg", (e3) => 360 * e3], ["grad", (e3) => 360 * e3 / 0.9], ["rad", (e3) => 360 * e3 / 180 * Math.PI], ["turn", (e3) => e3]]);
    Y = /* @__PURE__ */ new Map([["cm", x], ["mm", L], ["q", q], ["in", W], ["pc", $], ["pt", Z], ["px", z], ["ms", V], ["s", R], ["deg", P], ["grad", k], ["rad", G], ["turn", j], ["hz", O], ["khz", U]]);
    _ = /^none$/i;
    H = String.fromCodePoint(0);
    J = /* @__PURE__ */ new Map([["abs", function abs(e3, n3, t3) {
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
      const f3 = isNone(c3), p = isNone(v);
      if (f3 && p) return calc$1(calcWrapper(r3, s3), a3, o3);
      const C = solve(calc$1(calcWrapper(r3, s3), a3, o3), o3);
      if (-1 === C) return -1;
      if (f3) {
        const t3 = solve(calc$1(calcWrapper(r3, v), a3, o3), o3);
        return -1 === t3 ? -1 : solveMin((d3 = r3, g2 = C, D2 = t3, new FunctionNode([c.Function, "min(", d3.name[2], d3.name[3], { value: "min" }], [c.CloseParen, ")", d3.endToken[2], d3.endToken[3], void 0], [g2, new TokenNode([c.Comma, ",", ...sourceIndices(g2), void 0]), D2])), [C, t3], o3);
      }
      if (p) {
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
    K = /* @__PURE__ */ new Set(["nearest", "up", "down", "to-zero"]);
    Q = new Set(J.keys());
  }
});

// node_modules/@asamuzakjp/css-color/node_modules/lru-cache/dist/commonjs/index.min.js
var require_index_min = __commonJS({
  "node_modules/@asamuzakjp/css-color/node_modules/lru-cache/dist/commonjs/index.min.js"(exports2) {
    "use strict";
    Object.defineProperty(exports2, "__esModule", { value: true });
    exports2.LRUCache = void 0;
    var x2 = typeof performance == "object" && performance && typeof performance.now == "function" ? performance : Date;
    var U2 = /* @__PURE__ */ new Set();
    var R2 = typeof process == "object" && process ? process : {};
    var I = (a3, t3, e3, i3) => {
      typeof R2.emitWarning == "function" ? R2.emitWarning(a3, t3, e3, i3) : console.error(`[${e3}] ${t3}: ${a3}`);
    };
    var C = globalThis.AbortController;
    var L2 = globalThis.AbortSignal;
    if (typeof C > "u") {
      L2 = class {
        onabort;
        _onabort = [];
        reason;
        aborted = false;
        addEventListener(i3, s3) {
          this._onabort.push(s3);
        }
      }, C = class {
        constructor() {
          t3();
        }
        signal = new L2();
        abort(i3) {
          if (!this.signal.aborted) {
            this.signal.reason = i3, this.signal.aborted = true;
            for (let s3 of this.signal._onabort) s3(i3);
            this.signal.onabort?.(i3);
          }
        }
      };
      let a3 = R2.env?.LRU_CACHE_IGNORE_AC_WARNING !== "1", t3 = () => {
        a3 && (a3 = false, I("AbortController is not defined. If using lru-cache in node 14, load an AbortController polyfill from the `node-abort-controller` package. A minimal polyfill is provided for use by LRUCache.fetch(), but it should not be relied upon in other contexts (eg, passing it to other APIs that use AbortController/AbortSignal might have undesirable effects). You may disable this with LRU_CACHE_IGNORE_AC_WARNING=1 in the env.", "NO_ABORT_CONTROLLER", "ENOTSUP", t3));
      };
    }
    var G2 = (a3) => !U2.has(a3);
    var H2 = Symbol("type");
    var y2 = (a3) => a3 && a3 === Math.floor(a3) && a3 > 0 && isFinite(a3);
    var M2 = (a3) => y2(a3) ? a3 <= Math.pow(2, 8) ? Uint8Array : a3 <= Math.pow(2, 16) ? Uint16Array : a3 <= Math.pow(2, 32) ? Uint32Array : a3 <= Number.MAX_SAFE_INTEGER ? z2 : null : null;
    var z2 = class extends Array {
      constructor(t3) {
        super(t3), this.fill(0);
      }
    };
    var W2 = class a3 {
      heap;
      length;
      static #o = false;
      static create(t3) {
        let e3 = M2(t3);
        if (!e3) return [];
        a3.#o = true;
        let i3 = new a3(t3, e3);
        return a3.#o = false, i3;
      }
      constructor(t3, e3) {
        if (!a3.#o) throw new TypeError("instantiate Stack using Stack.create(n)");
        this.heap = new e3(t3), this.length = 0;
      }
      push(t3) {
        this.heap[this.length++] = t3;
      }
      pop() {
        return this.heap[--this.length];
      }
    };
    var D2 = class a3 {
      #o;
      #c;
      #w;
      #C;
      #S;
      #L;
      #U;
      #m;
      get perf() {
        return this.#m;
      }
      ttl;
      ttlResolution;
      ttlAutopurge;
      updateAgeOnGet;
      updateAgeOnHas;
      allowStale;
      noDisposeOnSet;
      noUpdateTTL;
      maxEntrySize;
      sizeCalculation;
      noDeleteOnFetchRejection;
      noDeleteOnStaleGet;
      allowStaleOnFetchAbort;
      allowStaleOnFetchRejection;
      ignoreFetchAbort;
      #n;
      #_;
      #s;
      #i;
      #t;
      #a;
      #u;
      #l;
      #h;
      #b;
      #r;
      #y;
      #A;
      #d;
      #g;
      #T;
      #v;
      #f;
      #I;
      static unsafeExposeInternals(t3) {
        return { starts: t3.#A, ttls: t3.#d, autopurgeTimers: t3.#g, sizes: t3.#y, keyMap: t3.#s, keyList: t3.#i, valList: t3.#t, next: t3.#a, prev: t3.#u, get head() {
          return t3.#l;
        }, get tail() {
          return t3.#h;
        }, free: t3.#b, isBackgroundFetch: (e3) => t3.#e(e3), backgroundFetch: (e3, i3, s3, h2) => t3.#G(e3, i3, s3, h2), moveToTail: (e3) => t3.#D(e3), indexes: (e3) => t3.#F(e3), rindexes: (e3) => t3.#O(e3), isStale: (e3) => t3.#p(e3) };
      }
      get max() {
        return this.#o;
      }
      get maxSize() {
        return this.#c;
      }
      get calculatedSize() {
        return this.#_;
      }
      get size() {
        return this.#n;
      }
      get fetchMethod() {
        return this.#L;
      }
      get memoMethod() {
        return this.#U;
      }
      get dispose() {
        return this.#w;
      }
      get onInsert() {
        return this.#C;
      }
      get disposeAfter() {
        return this.#S;
      }
      constructor(t3) {
        let { max: e3 = 0, ttl: i3, ttlResolution: s3 = 1, ttlAutopurge: h2, updateAgeOnGet: n3, updateAgeOnHas: o3, allowStale: r3, dispose: f3, onInsert: m2, disposeAfter: c3, noDisposeOnSet: d3, noUpdateTTL: g2, maxSize: A = 0, maxEntrySize: p = 0, sizeCalculation: _3, fetchMethod: l2, memoMethod: w, noDeleteOnFetchRejection: b2, noDeleteOnStaleGet: S, allowStaleOnFetchRejection: u3, allowStaleOnFetchAbort: T2, ignoreFetchAbort: F, perf: v } = t3;
        if (v !== void 0 && typeof v?.now != "function") throw new TypeError("perf option must have a now() method if specified");
        if (this.#m = v ?? x2, e3 !== 0 && !y2(e3)) throw new TypeError("max option must be a nonnegative integer");
        let O2 = e3 ? M2(e3) : Array;
        if (!O2) throw new Error("invalid max value: " + e3);
        if (this.#o = e3, this.#c = A, this.maxEntrySize = p || this.#c, this.sizeCalculation = _3, this.sizeCalculation) {
          if (!this.#c && !this.maxEntrySize) throw new TypeError("cannot set sizeCalculation without setting maxSize or maxEntrySize");
          if (typeof this.sizeCalculation != "function") throw new TypeError("sizeCalculation set to non-function");
        }
        if (w !== void 0 && typeof w != "function") throw new TypeError("memoMethod must be a function if defined");
        if (this.#U = w, l2 !== void 0 && typeof l2 != "function") throw new TypeError("fetchMethod must be a function if specified");
        if (this.#L = l2, this.#v = !!l2, this.#s = /* @__PURE__ */ new Map(), this.#i = new Array(e3).fill(void 0), this.#t = new Array(e3).fill(void 0), this.#a = new O2(e3), this.#u = new O2(e3), this.#l = 0, this.#h = 0, this.#b = W2.create(e3), this.#n = 0, this.#_ = 0, typeof f3 == "function" && (this.#w = f3), typeof m2 == "function" && (this.#C = m2), typeof c3 == "function" ? (this.#S = c3, this.#r = []) : (this.#S = void 0, this.#r = void 0), this.#T = !!this.#w, this.#I = !!this.#C, this.#f = !!this.#S, this.noDisposeOnSet = !!d3, this.noUpdateTTL = !!g2, this.noDeleteOnFetchRejection = !!b2, this.allowStaleOnFetchRejection = !!u3, this.allowStaleOnFetchAbort = !!T2, this.ignoreFetchAbort = !!F, this.maxEntrySize !== 0) {
          if (this.#c !== 0 && !y2(this.#c)) throw new TypeError("maxSize must be a positive integer if specified");
          if (!y2(this.maxEntrySize)) throw new TypeError("maxEntrySize must be a positive integer if specified");
          this.#B();
        }
        if (this.allowStale = !!r3, this.noDeleteOnStaleGet = !!S, this.updateAgeOnGet = !!n3, this.updateAgeOnHas = !!o3, this.ttlResolution = y2(s3) || s3 === 0 ? s3 : 1, this.ttlAutopurge = !!h2, this.ttl = i3 || 0, this.ttl) {
          if (!y2(this.ttl)) throw new TypeError("ttl must be a positive integer if specified");
          this.#j();
        }
        if (this.#o === 0 && this.ttl === 0 && this.#c === 0) throw new TypeError("At least one of max, maxSize, or ttl is required");
        if (!this.ttlAutopurge && !this.#o && !this.#c) {
          let E = "LRU_CACHE_UNBOUNDED";
          G2(E) && (U2.add(E), I("TTL caching without ttlAutopurge, max, or maxSize can result in unbounded memory consumption.", "UnboundedCacheWarning", E, a3));
        }
      }
      getRemainingTTL(t3) {
        return this.#s.has(t3) ? 1 / 0 : 0;
      }
      #j() {
        let t3 = new z2(this.#o), e3 = new z2(this.#o);
        this.#d = t3, this.#A = e3;
        let i3 = this.ttlAutopurge ? new Array(this.#o) : void 0;
        this.#g = i3, this.#N = (n3, o3, r3 = this.#m.now()) => {
          if (e3[n3] = o3 !== 0 ? r3 : 0, t3[n3] = o3, i3?.[n3] && (clearTimeout(i3[n3]), i3[n3] = void 0), o3 !== 0 && i3) {
            let f3 = setTimeout(() => {
              this.#p(n3) && this.#E(this.#i[n3], "expire");
            }, o3 + 1);
            f3.unref && f3.unref(), i3[n3] = f3;
          }
        }, this.#R = (n3) => {
          e3[n3] = t3[n3] !== 0 ? this.#m.now() : 0;
        }, this.#z = (n3, o3) => {
          if (t3[o3]) {
            let r3 = t3[o3], f3 = e3[o3];
            if (!r3 || !f3) return;
            n3.ttl = r3, n3.start = f3, n3.now = s3 || h2();
            let m2 = n3.now - f3;
            n3.remainingTTL = r3 - m2;
          }
        };
        let s3 = 0, h2 = () => {
          let n3 = this.#m.now();
          if (this.ttlResolution > 0) {
            s3 = n3;
            let o3 = setTimeout(() => s3 = 0, this.ttlResolution);
            o3.unref && o3.unref();
          }
          return n3;
        };
        this.getRemainingTTL = (n3) => {
          let o3 = this.#s.get(n3);
          if (o3 === void 0) return 0;
          let r3 = t3[o3], f3 = e3[o3];
          if (!r3 || !f3) return 1 / 0;
          let m2 = (s3 || h2()) - f3;
          return r3 - m2;
        }, this.#p = (n3) => {
          let o3 = e3[n3], r3 = t3[n3];
          return !!r3 && !!o3 && (s3 || h2()) - o3 > r3;
        };
      }
      #R = () => {
      };
      #z = () => {
      };
      #N = () => {
      };
      #p = () => false;
      #B() {
        let t3 = new z2(this.#o);
        this.#_ = 0, this.#y = t3, this.#W = (e3) => {
          this.#_ -= t3[e3], t3[e3] = 0;
        }, this.#P = (e3, i3, s3, h2) => {
          if (this.#e(i3)) return 0;
          if (!y2(s3)) if (h2) {
            if (typeof h2 != "function") throw new TypeError("sizeCalculation must be a function");
            if (s3 = h2(i3, e3), !y2(s3)) throw new TypeError("sizeCalculation return invalid (expect positive integer)");
          } else throw new TypeError("invalid size value (must be positive integer). When maxSize or maxEntrySize is used, sizeCalculation or size must be set.");
          return s3;
        }, this.#M = (e3, i3, s3) => {
          if (t3[e3] = i3, this.#c) {
            let h2 = this.#c - t3[e3];
            for (; this.#_ > h2; ) this.#x(true);
          }
          this.#_ += t3[e3], s3 && (s3.entrySize = i3, s3.totalCalculatedSize = this.#_);
        };
      }
      #W = (t3) => {
      };
      #M = (t3, e3, i3) => {
      };
      #P = (t3, e3, i3, s3) => {
        if (i3 || s3) throw new TypeError("cannot set size without setting maxSize or maxEntrySize on cache");
        return 0;
      };
      *#F({ allowStale: t3 = this.allowStale } = {}) {
        if (this.#n) for (let e3 = this.#h; !(!this.#H(e3) || ((t3 || !this.#p(e3)) && (yield e3), e3 === this.#l)); ) e3 = this.#u[e3];
      }
      *#O({ allowStale: t3 = this.allowStale } = {}) {
        if (this.#n) for (let e3 = this.#l; !(!this.#H(e3) || ((t3 || !this.#p(e3)) && (yield e3), e3 === this.#h)); ) e3 = this.#a[e3];
      }
      #H(t3) {
        return t3 !== void 0 && this.#s.get(this.#i[t3]) === t3;
      }
      *entries() {
        for (let t3 of this.#F()) this.#t[t3] !== void 0 && this.#i[t3] !== void 0 && !this.#e(this.#t[t3]) && (yield [this.#i[t3], this.#t[t3]]);
      }
      *rentries() {
        for (let t3 of this.#O()) this.#t[t3] !== void 0 && this.#i[t3] !== void 0 && !this.#e(this.#t[t3]) && (yield [this.#i[t3], this.#t[t3]]);
      }
      *keys() {
        for (let t3 of this.#F()) {
          let e3 = this.#i[t3];
          e3 !== void 0 && !this.#e(this.#t[t3]) && (yield e3);
        }
      }
      *rkeys() {
        for (let t3 of this.#O()) {
          let e3 = this.#i[t3];
          e3 !== void 0 && !this.#e(this.#t[t3]) && (yield e3);
        }
      }
      *values() {
        for (let t3 of this.#F()) this.#t[t3] !== void 0 && !this.#e(this.#t[t3]) && (yield this.#t[t3]);
      }
      *rvalues() {
        for (let t3 of this.#O()) this.#t[t3] !== void 0 && !this.#e(this.#t[t3]) && (yield this.#t[t3]);
      }
      [Symbol.iterator]() {
        return this.entries();
      }
      [Symbol.toStringTag] = "LRUCache";
      find(t3, e3 = {}) {
        for (let i3 of this.#F()) {
          let s3 = this.#t[i3], h2 = this.#e(s3) ? s3.__staleWhileFetching : s3;
          if (h2 !== void 0 && t3(h2, this.#i[i3], this)) return this.get(this.#i[i3], e3);
        }
      }
      forEach(t3, e3 = this) {
        for (let i3 of this.#F()) {
          let s3 = this.#t[i3], h2 = this.#e(s3) ? s3.__staleWhileFetching : s3;
          h2 !== void 0 && t3.call(e3, h2, this.#i[i3], this);
        }
      }
      rforEach(t3, e3 = this) {
        for (let i3 of this.#O()) {
          let s3 = this.#t[i3], h2 = this.#e(s3) ? s3.__staleWhileFetching : s3;
          h2 !== void 0 && t3.call(e3, h2, this.#i[i3], this);
        }
      }
      purgeStale() {
        let t3 = false;
        for (let e3 of this.#O({ allowStale: true })) this.#p(e3) && (this.#E(this.#i[e3], "expire"), t3 = true);
        return t3;
      }
      info(t3) {
        let e3 = this.#s.get(t3);
        if (e3 === void 0) return;
        let i3 = this.#t[e3], s3 = this.#e(i3) ? i3.__staleWhileFetching : i3;
        if (s3 === void 0) return;
        let h2 = { value: s3 };
        if (this.#d && this.#A) {
          let n3 = this.#d[e3], o3 = this.#A[e3];
          if (n3 && o3) {
            let r3 = n3 - (this.#m.now() - o3);
            h2.ttl = r3, h2.start = Date.now();
          }
        }
        return this.#y && (h2.size = this.#y[e3]), h2;
      }
      dump() {
        let t3 = [];
        for (let e3 of this.#F({ allowStale: true })) {
          let i3 = this.#i[e3], s3 = this.#t[e3], h2 = this.#e(s3) ? s3.__staleWhileFetching : s3;
          if (h2 === void 0 || i3 === void 0) continue;
          let n3 = { value: h2 };
          if (this.#d && this.#A) {
            n3.ttl = this.#d[e3];
            let o3 = this.#m.now() - this.#A[e3];
            n3.start = Math.floor(Date.now() - o3);
          }
          this.#y && (n3.size = this.#y[e3]), t3.unshift([i3, n3]);
        }
        return t3;
      }
      load(t3) {
        this.clear();
        for (let [e3, i3] of t3) {
          if (i3.start) {
            let s3 = Date.now() - i3.start;
            i3.start = this.#m.now() - s3;
          }
          this.set(e3, i3.value, i3);
        }
      }
      set(t3, e3, i3 = {}) {
        if (e3 === void 0) return this.delete(t3), this;
        let { ttl: s3 = this.ttl, start: h2, noDisposeOnSet: n3 = this.noDisposeOnSet, sizeCalculation: o3 = this.sizeCalculation, status: r3 } = i3, { noUpdateTTL: f3 = this.noUpdateTTL } = i3, m2 = this.#P(t3, e3, i3.size || 0, o3);
        if (this.maxEntrySize && m2 > this.maxEntrySize) return r3 && (r3.set = "miss", r3.maxEntrySizeExceeded = true), this.#E(t3, "set"), this;
        let c3 = this.#n === 0 ? void 0 : this.#s.get(t3);
        if (c3 === void 0) c3 = this.#n === 0 ? this.#h : this.#b.length !== 0 ? this.#b.pop() : this.#n === this.#o ? this.#x(false) : this.#n, this.#i[c3] = t3, this.#t[c3] = e3, this.#s.set(t3, c3), this.#a[this.#h] = c3, this.#u[c3] = this.#h, this.#h = c3, this.#n++, this.#M(c3, m2, r3), r3 && (r3.set = "add"), f3 = false, this.#I && this.#C?.(e3, t3, "add");
        else {
          this.#D(c3);
          let d3 = this.#t[c3];
          if (e3 !== d3) {
            if (this.#v && this.#e(d3)) {
              d3.__abortController.abort(new Error("replaced"));
              let { __staleWhileFetching: g2 } = d3;
              g2 !== void 0 && !n3 && (this.#T && this.#w?.(g2, t3, "set"), this.#f && this.#r?.push([g2, t3, "set"]));
            } else n3 || (this.#T && this.#w?.(d3, t3, "set"), this.#f && this.#r?.push([d3, t3, "set"]));
            if (this.#W(c3), this.#M(c3, m2, r3), this.#t[c3] = e3, r3) {
              r3.set = "replace";
              let g2 = d3 && this.#e(d3) ? d3.__staleWhileFetching : d3;
              g2 !== void 0 && (r3.oldValue = g2);
            }
          } else r3 && (r3.set = "update");
          this.#I && this.onInsert?.(e3, t3, e3 === d3 ? "update" : "replace");
        }
        if (s3 !== 0 && !this.#d && this.#j(), this.#d && (f3 || this.#N(c3, s3, h2), r3 && this.#z(r3, c3)), !n3 && this.#f && this.#r) {
          let d3 = this.#r, g2;
          for (; g2 = d3?.shift(); ) this.#S?.(...g2);
        }
        return this;
      }
      pop() {
        try {
          for (; this.#n; ) {
            let t3 = this.#t[this.#l];
            if (this.#x(true), this.#e(t3)) {
              if (t3.__staleWhileFetching) return t3.__staleWhileFetching;
            } else if (t3 !== void 0) return t3;
          }
        } finally {
          if (this.#f && this.#r) {
            let t3 = this.#r, e3;
            for (; e3 = t3?.shift(); ) this.#S?.(...e3);
          }
        }
      }
      #x(t3) {
        let e3 = this.#l, i3 = this.#i[e3], s3 = this.#t[e3];
        return this.#v && this.#e(s3) ? s3.__abortController.abort(new Error("evicted")) : (this.#T || this.#f) && (this.#T && this.#w?.(s3, i3, "evict"), this.#f && this.#r?.push([s3, i3, "evict"])), this.#W(e3), this.#g?.[e3] && (clearTimeout(this.#g[e3]), this.#g[e3] = void 0), t3 && (this.#i[e3] = void 0, this.#t[e3] = void 0, this.#b.push(e3)), this.#n === 1 ? (this.#l = this.#h = 0, this.#b.length = 0) : this.#l = this.#a[e3], this.#s.delete(i3), this.#n--, e3;
      }
      has(t3, e3 = {}) {
        let { updateAgeOnHas: i3 = this.updateAgeOnHas, status: s3 } = e3, h2 = this.#s.get(t3);
        if (h2 !== void 0) {
          let n3 = this.#t[h2];
          if (this.#e(n3) && n3.__staleWhileFetching === void 0) return false;
          if (this.#p(h2)) s3 && (s3.has = "stale", this.#z(s3, h2));
          else return i3 && this.#R(h2), s3 && (s3.has = "hit", this.#z(s3, h2)), true;
        } else s3 && (s3.has = "miss");
        return false;
      }
      peek(t3, e3 = {}) {
        let { allowStale: i3 = this.allowStale } = e3, s3 = this.#s.get(t3);
        if (s3 === void 0 || !i3 && this.#p(s3)) return;
        let h2 = this.#t[s3];
        return this.#e(h2) ? h2.__staleWhileFetching : h2;
      }
      #G(t3, e3, i3, s3) {
        let h2 = e3 === void 0 ? void 0 : this.#t[e3];
        if (this.#e(h2)) return h2;
        let n3 = new C(), { signal: o3 } = i3;
        o3?.addEventListener("abort", () => n3.abort(o3.reason), { signal: n3.signal });
        let r3 = { signal: n3.signal, options: i3, context: s3 }, f3 = (p, _3 = false) => {
          let { aborted: l2 } = n3.signal, w = i3.ignoreFetchAbort && p !== void 0, b2 = i3.ignoreFetchAbort || !!(i3.allowStaleOnFetchAbort && p !== void 0);
          if (i3.status && (l2 && !_3 ? (i3.status.fetchAborted = true, i3.status.fetchError = n3.signal.reason, w && (i3.status.fetchAbortIgnored = true)) : i3.status.fetchResolved = true), l2 && !w && !_3) return c3(n3.signal.reason, b2);
          let S = g2, u3 = this.#t[e3];
          return (u3 === g2 || w && _3 && u3 === void 0) && (p === void 0 ? S.__staleWhileFetching !== void 0 ? this.#t[e3] = S.__staleWhileFetching : this.#E(t3, "fetch") : (i3.status && (i3.status.fetchUpdated = true), this.set(t3, p, r3.options))), p;
        }, m2 = (p) => (i3.status && (i3.status.fetchRejected = true, i3.status.fetchError = p), c3(p, false)), c3 = (p, _3) => {
          let { aborted: l2 } = n3.signal, w = l2 && i3.allowStaleOnFetchAbort, b2 = w || i3.allowStaleOnFetchRejection, S = b2 || i3.noDeleteOnFetchRejection, u3 = g2;
          if (this.#t[e3] === g2 && (!S || !_3 && u3.__staleWhileFetching === void 0 ? this.#E(t3, "fetch") : w || (this.#t[e3] = u3.__staleWhileFetching)), b2) return i3.status && u3.__staleWhileFetching !== void 0 && (i3.status.returnedStale = true), u3.__staleWhileFetching;
          if (u3.__returned === u3) throw p;
        }, d3 = (p, _3) => {
          let l2 = this.#L?.(t3, h2, r3);
          l2 && l2 instanceof Promise && l2.then((w) => p(w === void 0 ? void 0 : w), _3), n3.signal.addEventListener("abort", () => {
            (!i3.ignoreFetchAbort || i3.allowStaleOnFetchAbort) && (p(void 0), i3.allowStaleOnFetchAbort && (p = (w) => f3(w, true)));
          });
        };
        i3.status && (i3.status.fetchDispatched = true);
        let g2 = new Promise(d3).then(f3, m2), A = Object.assign(g2, { __abortController: n3, __staleWhileFetching: h2, __returned: void 0 });
        return e3 === void 0 ? (this.set(t3, A, { ...r3.options, status: void 0 }), e3 = this.#s.get(t3)) : this.#t[e3] = A, A;
      }
      #e(t3) {
        if (!this.#v) return false;
        let e3 = t3;
        return !!e3 && e3 instanceof Promise && e3.hasOwnProperty("__staleWhileFetching") && e3.__abortController instanceof C;
      }
      async fetch(t3, e3 = {}) {
        let { allowStale: i3 = this.allowStale, updateAgeOnGet: s3 = this.updateAgeOnGet, noDeleteOnStaleGet: h2 = this.noDeleteOnStaleGet, ttl: n3 = this.ttl, noDisposeOnSet: o3 = this.noDisposeOnSet, size: r3 = 0, sizeCalculation: f3 = this.sizeCalculation, noUpdateTTL: m2 = this.noUpdateTTL, noDeleteOnFetchRejection: c3 = this.noDeleteOnFetchRejection, allowStaleOnFetchRejection: d3 = this.allowStaleOnFetchRejection, ignoreFetchAbort: g2 = this.ignoreFetchAbort, allowStaleOnFetchAbort: A = this.allowStaleOnFetchAbort, context: p, forceRefresh: _3 = false, status: l2, signal: w } = e3;
        if (!this.#v) return l2 && (l2.fetch = "get"), this.get(t3, { allowStale: i3, updateAgeOnGet: s3, noDeleteOnStaleGet: h2, status: l2 });
        let b2 = { allowStale: i3, updateAgeOnGet: s3, noDeleteOnStaleGet: h2, ttl: n3, noDisposeOnSet: o3, size: r3, sizeCalculation: f3, noUpdateTTL: m2, noDeleteOnFetchRejection: c3, allowStaleOnFetchRejection: d3, allowStaleOnFetchAbort: A, ignoreFetchAbort: g2, status: l2, signal: w }, S = this.#s.get(t3);
        if (S === void 0) {
          l2 && (l2.fetch = "miss");
          let u3 = this.#G(t3, S, b2, p);
          return u3.__returned = u3;
        } else {
          let u3 = this.#t[S];
          if (this.#e(u3)) {
            let E = i3 && u3.__staleWhileFetching !== void 0;
            return l2 && (l2.fetch = "inflight", E && (l2.returnedStale = true)), E ? u3.__staleWhileFetching : u3.__returned = u3;
          }
          let T2 = this.#p(S);
          if (!_3 && !T2) return l2 && (l2.fetch = "hit"), this.#D(S), s3 && this.#R(S), l2 && this.#z(l2, S), u3;
          let F = this.#G(t3, S, b2, p), O2 = F.__staleWhileFetching !== void 0 && i3;
          return l2 && (l2.fetch = T2 ? "stale" : "refresh", O2 && T2 && (l2.returnedStale = true)), O2 ? F.__staleWhileFetching : F.__returned = F;
        }
      }
      async forceFetch(t3, e3 = {}) {
        let i3 = await this.fetch(t3, e3);
        if (i3 === void 0) throw new Error("fetch() returned undefined");
        return i3;
      }
      memo(t3, e3 = {}) {
        let i3 = this.#U;
        if (!i3) throw new Error("no memoMethod provided to constructor");
        let { context: s3, forceRefresh: h2, ...n3 } = e3, o3 = this.get(t3, n3);
        if (!h2 && o3 !== void 0) return o3;
        let r3 = i3(t3, o3, { options: n3, context: s3 });
        return this.set(t3, r3, n3), r3;
      }
      get(t3, e3 = {}) {
        let { allowStale: i3 = this.allowStale, updateAgeOnGet: s3 = this.updateAgeOnGet, noDeleteOnStaleGet: h2 = this.noDeleteOnStaleGet, status: n3 } = e3, o3 = this.#s.get(t3);
        if (o3 !== void 0) {
          let r3 = this.#t[o3], f3 = this.#e(r3);
          return n3 && this.#z(n3, o3), this.#p(o3) ? (n3 && (n3.get = "stale"), f3 ? (n3 && i3 && r3.__staleWhileFetching !== void 0 && (n3.returnedStale = true), i3 ? r3.__staleWhileFetching : void 0) : (h2 || this.#E(t3, "expire"), n3 && i3 && (n3.returnedStale = true), i3 ? r3 : void 0)) : (n3 && (n3.get = "hit"), f3 ? r3.__staleWhileFetching : (this.#D(o3), s3 && this.#R(o3), r3));
        } else n3 && (n3.get = "miss");
      }
      #k(t3, e3) {
        this.#u[e3] = t3, this.#a[t3] = e3;
      }
      #D(t3) {
        t3 !== this.#h && (t3 === this.#l ? this.#l = this.#a[t3] : this.#k(this.#u[t3], this.#a[t3]), this.#k(this.#h, t3), this.#h = t3);
      }
      delete(t3) {
        return this.#E(t3, "delete");
      }
      #E(t3, e3) {
        let i3 = false;
        if (this.#n !== 0) {
          let s3 = this.#s.get(t3);
          if (s3 !== void 0) if (this.#g?.[s3] && (clearTimeout(this.#g?.[s3]), this.#g[s3] = void 0), i3 = true, this.#n === 1) this.#V(e3);
          else {
            this.#W(s3);
            let h2 = this.#t[s3];
            if (this.#e(h2) ? h2.__abortController.abort(new Error("deleted")) : (this.#T || this.#f) && (this.#T && this.#w?.(h2, t3, e3), this.#f && this.#r?.push([h2, t3, e3])), this.#s.delete(t3), this.#i[s3] = void 0, this.#t[s3] = void 0, s3 === this.#h) this.#h = this.#u[s3];
            else if (s3 === this.#l) this.#l = this.#a[s3];
            else {
              let n3 = this.#u[s3];
              this.#a[n3] = this.#a[s3];
              let o3 = this.#a[s3];
              this.#u[o3] = this.#u[s3];
            }
            this.#n--, this.#b.push(s3);
          }
        }
        if (this.#f && this.#r?.length) {
          let s3 = this.#r, h2;
          for (; h2 = s3?.shift(); ) this.#S?.(...h2);
        }
        return i3;
      }
      clear() {
        return this.#V("delete");
      }
      #V(t3) {
        for (let e3 of this.#O({ allowStale: true })) {
          let i3 = this.#t[e3];
          if (this.#e(i3)) i3.__abortController.abort(new Error("deleted"));
          else {
            let s3 = this.#i[e3];
            this.#T && this.#w?.(i3, s3, t3), this.#f && this.#r?.push([i3, s3, t3]);
          }
        }
        if (this.#s.clear(), this.#t.fill(void 0), this.#i.fill(void 0), this.#d && this.#A) {
          this.#d.fill(0), this.#A.fill(0);
          for (let e3 of this.#g ?? []) e3 !== void 0 && clearTimeout(e3);
          this.#g?.fill(void 0);
        }
        if (this.#y && this.#y.fill(0), this.#l = 0, this.#h = 0, this.#b.length = 0, this.#_ = 0, this.#n = 0, this.#f && this.#r) {
          let e3 = this.#r, i3;
          for (; i3 = e3?.shift(); ) this.#S?.(...i3);
        }
      }
    };
    exports2.LRUCache = D2;
  }
});

// node_modules/@csstools/color-helpers/dist/index.mjs
function multiplyMatrices(t3, n3) {
  return [t3[0] * n3[0] + t3[1] * n3[1] + t3[2] * n3[2], t3[3] * n3[0] + t3[4] * n3[1] + t3[5] * n3[2], t3[6] * n3[0] + t3[7] * n3[1] + t3[8] * n3[2]];
}
function D50_to_D65(n3) {
  return multiplyMatrices(t2, n3);
}
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
function Lab_to_XYZ(t3) {
  const n3 = 24389 / 27, o3 = 216 / 24389, e3 = (t3[0] + 16) / 116, a3 = t3[1] / 500 + e3, r3 = e3 - t3[2] / 200;
  return [(Math.pow(a3, 3) > o3 ? Math.pow(a3, 3) : (116 * a3 - 16) / n3) * _2[0], (t3[0] > 8 ? Math.pow((t3[0] + 16) / 116, 3) : t3[0] / n3) * _2[1], (Math.pow(r3, 3) > o3 ? Math.pow(r3, 3) : (116 * r3 - 16) / n3) * _2[2]];
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
function OKLab_to_XYZ(t3) {
  const n3 = multiplyMatrices(e2, t3);
  return multiplyMatrices(o2, [n3[0] ** 3, n3[1] ** 3, n3[2] ** 3]);
}
function XYZ_to_Lab(t3) {
  const n3 = compute_f(t3[0] / _2[0]), o3 = compute_f(t3[1] / _2[1]);
  return [116 * o3 - 16, 500 * (n3 - o3), 200 * (o3 - compute_f(t3[2] / _2[2]))];
}
function compute_f(t3) {
  return t3 > a2 ? Math.cbrt(t3) : (r2 * t3 + 16) / 116;
}
function XYZ_to_OKLab(t3) {
  const n3 = multiplyMatrices(l, t3);
  return multiplyMatrices(i2, [Math.cbrt(n3[0]), Math.cbrt(n3[1]), Math.cbrt(n3[2])]);
}
function XYZ_to_lin_P3(t3) {
  return multiplyMatrices(u2, t3);
}
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
function lin_P3_to_XYZ(t3) {
  return multiplyMatrices(g, t3);
}
function lin_ProPhoto_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return _3 <= X ? t3 / 16 : n3 * Math.pow(_3, 1.8);
}
function lin_a98rgb_channel(t3) {
  const n3 = t3 < 0 ? -1 : 1, _3 = Math.abs(t3);
  return n3 * Math.pow(_3, 563 / 256);
}
function lin_sRGB_to_XYZ(t3) {
  return multiplyMatrices(f2, t3);
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
  return n3 = [lin_a98rgb_channel((_3 = n3)[0]), lin_a98rgb_channel(_3[1]), lin_a98rgb_channel(_3[2])], n3 = multiplyMatrices(Z2, n3), n3 = D65_to_D50(n3), n3;
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
  return n3 = [lin_ProPhoto_channel((_3 = n3)[0]), lin_ProPhoto_channel(_3[1]), lin_ProPhoto_channel(_3[2])], n3 = multiplyMatrices(Y2, n3), n3;
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
function luminance(t3) {
  const [n3, _3, o3] = t3.map((t4) => t4 <= 0.04045 ? t4 / 12.92 : Math.pow((t4 + 0.055) / 1.055, 2.4));
  return 0.2126 * n3 + 0.7152 * _3 + 0.0722 * o3;
}
function contrast_ratio_wcag_2_1(t3, n3) {
  const _3 = luminance(t3), o3 = luminance(n3);
  return (Math.max(_3, o3) + 0.05) / (Math.min(_3, o3) + 0.05);
}
var t2, n2, _2, o2, e2, a2, r2, l, i2, c2, u2, s2, h, m, D, b, g, X, Y2, Z2, f2, d2;
var init_dist4 = __esm({
  "node_modules/@csstools/color-helpers/dist/index.mjs"() {
    t2 = [0.955473421488075, -0.02309845494876471, 0.06325924320057072, -0.0283697093338637, 1.0099953980813041, 0.021041441191917323, 0.012314014864481998, -0.020507649298898964, 1.330365926242124];
    n2 = [1.0479297925449969, 0.022946870601609652, -0.05019226628920524, 0.02962780877005599, 0.9904344267538799, -0.017073799063418826, -0.009243040646204504, 0.015055191490298152, 0.7518742814281371];
    _2 = [0.3457 / 0.3585, 1, 0.2958 / 0.3585];
    o2 = [1.2268798758459243, -0.5578149944602171, 0.2813910456659647, -0.0405757452148008, 1.112286803280317, -0.0717110580655164, -0.0763729366746601, -0.4214933324022432, 1.5869240198367816];
    e2 = [1, 0.3963377773761749, 0.2158037573099136, 1, -0.1055613458156586, -0.0638541728258133, 1, -0.0894841775298119, -1.2914855480194092];
    a2 = 216 / 24389;
    r2 = 24389 / 27;
    l = [0.819022437996703, 0.3619062600528904, -0.1288737815209879, 0.0329836539323885, 0.9292868615863434, 0.0361446663506424, 0.0481771893596242, 0.2642395317527308, 0.6335478284694309];
    i2 = [0.210454268309314, 0.7936177747023054, -0.0040720430116193, 1.9779985324311684, -2.42859224204858, 0.450593709617411, 0.0259040424655478, 0.7827717124575296, -0.8086757549230774];
    c2 = [30757411 / 17917100, -6372589 / 17917100, -4539589 / 17917100, -0.666684351832489, 1.616481236634939, 467509 / 29648200, 792561 / 44930125, -1921689 / 44930125, 0.942103121235474];
    u2 = [446124 / 178915, -333277 / 357830, -72051 / 178915, -14852 / 17905, 63121 / 35810, 423 / 17905, 11844 / 330415, -50337 / 660830, 316169 / 330415];
    s2 = [1.3457868816471583, -0.25557208737979464, -0.05110186497554526, -0.5446307051249019, 1.5082477428451468, 0.02052744743642139, 0, 0, 1.2119675456389452];
    h = [1829569 / 896150, -506331 / 896150, -308931 / 896150, -851781 / 878810, 1648619 / 878810, 36519 / 878810, 16779 / 1248040, -147721 / 1248040, 1266979 / 1248040];
    m = [12831 / 3959, -329 / 214, -1974 / 3959, -851781 / 878810, 1648619 / 878810, 36519 / 878810, 705 / 12673, -2585 / 12673, 705 / 667];
    D = 1 / 512;
    b = [63426534 / 99577255, 20160776 / 139408157, 47086771 / 278816314, 26158966 / 99577255, 0.677998071518871, 8267143 / 139408157, 0, 19567812 / 697040785, 1.0609850577107909];
    g = [608311 / 1250200, 189793 / 714400, 198249 / 1000160, 35783 / 156275, 247089 / 357200, 198249 / 2500400, 0, 32229 / 714400, 5220557 / 5000800];
    X = 16 / 512;
    Y2 = [0.7977666449006423, 0.13518129740053308, 0.0313477341283922, 0.2880748288194013, 0.711835234241873, 8993693872564e-17, 0, 0, 0.8251046025104602];
    Z2 = [573536 / 994567, 263643 / 1420810, 187206 / 994567, 591459 / 1989134, 6239551 / 9945670, 374412 / 4972835, 53769 / 1989134, 351524 / 4972835, 4929758 / 4972835];
    f2 = [506752 / 1228815, 87881 / 245763, 12673 / 70218, 87098 / 409605, 175762 / 245763, 12673 / 175545, 7918 / 409605, 87881 / 737289, 1001167 / 1053270];
    d2 = { aliceblue: [240, 248, 255], antiquewhite: [250, 235, 215], aqua: [0, 255, 255], aquamarine: [127, 255, 212], azure: [240, 255, 255], beige: [245, 245, 220], bisque: [255, 228, 196], black: [0, 0, 0], blanchedalmond: [255, 235, 205], blue: [0, 0, 255], blueviolet: [138, 43, 226], brown: [165, 42, 42], burlywood: [222, 184, 135], cadetblue: [95, 158, 160], chartreuse: [127, 255, 0], chocolate: [210, 105, 30], coral: [255, 127, 80], cornflowerblue: [100, 149, 237], cornsilk: [255, 248, 220], crimson: [220, 20, 60], cyan: [0, 255, 255], darkblue: [0, 0, 139], darkcyan: [0, 139, 139], darkgoldenrod: [184, 134, 11], darkgray: [169, 169, 169], darkgreen: [0, 100, 0], darkgrey: [169, 169, 169], darkkhaki: [189, 183, 107], darkmagenta: [139, 0, 139], darkolivegreen: [85, 107, 47], darkorange: [255, 140, 0], darkorchid: [153, 50, 204], darkred: [139, 0, 0], darksalmon: [233, 150, 122], darkseagreen: [143, 188, 143], darkslateblue: [72, 61, 139], darkslategray: [47, 79, 79], darkslategrey: [47, 79, 79], darkturquoise: [0, 206, 209], darkviolet: [148, 0, 211], deeppink: [255, 20, 147], deepskyblue: [0, 191, 255], dimgray: [105, 105, 105], dimgrey: [105, 105, 105], dodgerblue: [30, 144, 255], firebrick: [178, 34, 34], floralwhite: [255, 250, 240], forestgreen: [34, 139, 34], fuchsia: [255, 0, 255], gainsboro: [220, 220, 220], ghostwhite: [248, 248, 255], gold: [255, 215, 0], goldenrod: [218, 165, 32], gray: [128, 128, 128], green: [0, 128, 0], greenyellow: [173, 255, 47], grey: [128, 128, 128], honeydew: [240, 255, 240], hotpink: [255, 105, 180], indianred: [205, 92, 92], indigo: [75, 0, 130], ivory: [255, 255, 240], khaki: [240, 230, 140], lavender: [230, 230, 250], lavenderblush: [255, 240, 245], lawngreen: [124, 252, 0], lemonchiffon: [255, 250, 205], lightblue: [173, 216, 230], lightcoral: [240, 128, 128], lightcyan: [224, 255, 255], lightgoldenrodyellow: [250, 250, 210], lightgray: [211, 211, 211], lightgreen: [144, 238, 144], lightgrey: [211, 211, 211], lightpink: [255, 182, 193], lightsalmon: [255, 160, 122], lightseagreen: [32, 178, 170], lightskyblue: [135, 206, 250], lightslategray: [119, 136, 153], lightslategrey: [119, 136, 153], lightsteelblue: [176, 196, 222], lightyellow: [255, 255, 224], lime: [0, 255, 0], limegreen: [50, 205, 50], linen: [250, 240, 230], magenta: [255, 0, 255], maroon: [128, 0, 0], mediumaquamarine: [102, 205, 170], mediumblue: [0, 0, 205], mediumorchid: [186, 85, 211], mediumpurple: [147, 112, 219], mediumseagreen: [60, 179, 113], mediumslateblue: [123, 104, 238], mediumspringgreen: [0, 250, 154], mediumturquoise: [72, 209, 204], mediumvioletred: [199, 21, 133], midnightblue: [25, 25, 112], mintcream: [245, 255, 250], mistyrose: [255, 228, 225], moccasin: [255, 228, 181], navajowhite: [255, 222, 173], navy: [0, 0, 128], oldlace: [253, 245, 230], olive: [128, 128, 0], olivedrab: [107, 142, 35], orange: [255, 165, 0], orangered: [255, 69, 0], orchid: [218, 112, 214], palegoldenrod: [238, 232, 170], palegreen: [152, 251, 152], paleturquoise: [175, 238, 238], palevioletred: [219, 112, 147], papayawhip: [255, 239, 213], peachpuff: [255, 218, 185], peru: [205, 133, 63], pink: [255, 192, 203], plum: [221, 160, 221], powderblue: [176, 224, 230], purple: [128, 0, 128], rebeccapurple: [102, 51, 153], red: [255, 0, 0], rosybrown: [188, 143, 143], royalblue: [65, 105, 225], saddlebrown: [139, 69, 19], salmon: [250, 128, 114], sandybrown: [244, 164, 96], seagreen: [46, 139, 87], seashell: [255, 245, 238], sienna: [160, 82, 45], silver: [192, 192, 192], skyblue: [135, 206, 235], slateblue: [106, 90, 205], slategray: [112, 128, 144], slategrey: [112, 128, 144], snow: [255, 250, 250], springgreen: [0, 255, 127], steelblue: [70, 130, 180], tan: [210, 180, 140], teal: [0, 128, 128], thistle: [216, 191, 216], tomato: [255, 99, 71], turquoise: [64, 224, 208], violet: [238, 130, 238], wheat: [245, 222, 179], white: [255, 255, 255], whitesmoke: [245, 245, 245], yellow: [255, 255, 0], yellowgreen: [154, 205, 50] };
  }
});

// node_modules/@csstools/css-color-parser/dist/index.mjs
var dist_exports4 = {};
__export(dist_exports4, {
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
function color$1(e3, a3) {
  const r3 = [], s3 = [], u3 = [], i3 = [];
  let c3, h2, m2 = false, p = false;
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
        m2 = toLowerCaseAZ2(v2.value[4].value), N.colorNotation = colorSpaceNameToColorNotation(m2), p && (p.colorNotation !== N.colorNotation && (p = colorDataTo(p, N.colorNotation)), c3 = normalizeRelativeColorDataChannels(p), h2 = noneToZeroInRelativeColorDataChannels(c3));
      } else if (b2 === r3 && 0 === r3.length && isTokenNode(v2) && isTokenIdent(v2.value) && "from" === toLowerCaseAZ2(v2.value[4].value)) {
        if (p) return false;
        if (m2) return false;
        for (; isWhitespaceNode(e3.value[o3 + 1]) || isCommentNode(e3.value[o3 + 1]); ) o3++;
        if (o3++, v2 = e3.value[o3], p = a3(v2), false === p) return false;
        p.syntaxFlags.has(me.Experimental) && N.syntaxFlags.add(me.Experimental), N.syntaxFlags.add(me.RelativeColorSyntax);
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
  let s3 = 0, u3 = 0, i3 = 0, c3 = 0, h2 = 0, m2 = 0, p = n3.alpha;
  if ("number" != typeof p) return false;
  let N = o3.alpha;
  if ("number" != typeof N) return false;
  p = Number.isNaN(p) ? N : p, N = Number.isNaN(N) ? p : N;
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
  i3 = premultiply(i3, p), h2 = premultiply(h2, p), c3 = premultiply(c3, N), m2 = premultiply(m2, N);
  let f3 = [0, 0, 0];
  const d3 = interpolate(p, N, l2);
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
  const p = a3(t3[0].value, 0, h2);
  if (!p || !isTokenNumber(p)) return false;
  const N = a3(u3[0].value, 1, h2);
  if (!N || !isTokenNumber(N)) return false;
  const b2 = a3(i3[0].value, 2, h2);
  if (!b2 || !isTokenNumber(b2)) return false;
  const v = [p, N, b2];
  if (1 === c3.length) if (h2.syntaxFlags.add(me.HasAlpha), isTokenNode(c3[0])) {
    const e4 = a3(c3[0].value, 3, h2);
    if (!e4 || !isTokenNumber(e4)) return false;
    v.push(e4);
  } else h2.alpha = c3[0];
  return h2.channels = [v[0][4].value, v[1][4].value, v[2][4].value], 4 === v.length && (h2.alpha = v[3][4].value), h2;
}
function threeChannelSpaceSeparated(e3, a3, r3, s3, u3) {
  const i3 = [], c3 = [], h2 = [], m2 = [];
  let p, N, b2 = false;
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
        b2.syntaxFlags.has(me.Experimental) && v.syntaxFlags.add(me.Experimental), v.syntaxFlags.add(me.RelativeColorSyntax), b2.colorNotation !== r3 && (b2 = colorDataTo(b2, r3)), p = normalizeRelativeColorDataChannels(b2), N = noneToZeroInRelativeColorDataChannels(p);
      } else {
        if (!isTokenNode(o3)) return false;
        if (isTokenIdent(o3.value) && p) {
          const e4 = o3.value[4].value.toLowerCase();
          if (p.has(e4)) {
            g2.push(new TokenNode(p.get(e4)));
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
  if (p && !p.has("alpha")) return false;
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
  else if (p && p.has("alpha")) {
    const e4 = a3(p.get("alpha"), 3, v);
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
    let p = e3.value[m2];
    if (isWhitespaceNode(p) || isCommentNode(p)) for (; isWhitespaceNode(e3.value[m2 + 1]) || isCommentNode(e3.value[m2 + 1]); ) m2++;
    else if (c3 && !u3 && !i3 && isTokenNode(p) && isTokenDelim(p.value) && "/" === p.value[4].value) u3 = true;
    else {
      if (isFunctionNode(p) && Q.has(toLowerCaseAZ2(p.getName()))) {
        const [[e4]] = calcFromComponentValues([[p]], { censorIntoStandardRepresentableValues: true, globals: s3, precision: -1, toCanonicalUnits: true, rawPercentages: true });
        if (!e4 || !isTokenNode(e4) || !isTokenNumeric(e4.value)) return false;
        Number.isNaN(e4.value[4].value) && (e4.value[4].value = 0), p = e4;
      }
      if (u3 || i3 || !isTokenNode(p) || !isTokenIdent(p.value) || "from" !== toLowerCaseAZ2(p.value[4].value)) {
        if (!u3) return false;
        if (i3) return false;
        if (isTokenNode(p)) {
          if (isTokenIdent(p.value) && "alpha" === toLowerCaseAZ2(p.value[4].value) && r3 && r3.has("alpha")) {
            h2.alpha = r3.get("alpha")[4].value, i3 = true;
            continue;
          }
          const e4 = normalize_Color_ChannelValues(p.value, 3, h2);
          if (!e4 || !isTokenNumber(e4)) return false;
          h2.alpha = new TokenNode(e4), i3 = true;
          continue;
        }
        if (isFunctionNode(p)) {
          const e4 = replaceComponentValues([[p]], (e5) => {
            if (isTokenNode(e5) && isTokenIdent(e5.value) && "alpha" === toLowerCaseAZ2(e5.value[4].value) && r3 && r3.has("alpha")) return new TokenNode(r3.get("alpha"));
          });
          h2.alpha = e4[0][0], i3 = true;
          continue;
        }
        return false;
      }
      if (c3) return false;
      for (; isWhitespaceNode(e3.value[m2 + 1]) || isCommentNode(e3.value[m2 + 1]); ) m2++;
      if (m2++, p = e3.value[m2], c3 = a3(p), false === c3) return false;
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
var he, me, pe, Ne, be, ve, ge, fe, de;
var init_dist5 = __esm({
  "node_modules/@csstools/css-color-parser/dist/index.mjs"() {
    init_dist();
    init_dist4();
    init_dist2();
    init_dist3();
    !function(e3) {
      e3.A98_RGB = "a98-rgb", e3.Display_P3 = "display-p3", e3.Linear_Display_P3 = "display-p3-linear", e3.HEX = "hex", e3.HSL = "hsl", e3.HWB = "hwb", e3.LCH = "lch", e3.Lab = "lab", e3.Linear_sRGB = "srgb-linear", e3.OKLCH = "oklch", e3.OKLab = "oklab", e3.ProPhoto_RGB = "prophoto-rgb", e3.RGB = "rgb", e3.sRGB = "srgb", e3.Rec2020 = "rec2020", e3.XYZ_D50 = "xyz-d50", e3.XYZ_D65 = "xyz-d65";
    }(he || (he = {})), function(e3) {
      e3.ColorKeyword = "color-keyword", e3.HasAlpha = "has-alpha", e3.HasDimensionValues = "has-dimension-values", e3.HasNoneKeywords = "has-none-keywords", e3.HasNumberValues = "has-number-values", e3.HasPercentageAlpha = "has-percentage-alpha", e3.HasPercentageValues = "has-percentage-values", e3.HasVariableAlpha = "has-variable-alpha", e3.Hex = "hex", e3.LegacyHSL = "legacy-hsl", e3.LegacyRGB = "legacy-rgb", e3.NamedColor = "named-color", e3.RelativeColorSyntax = "relative-color-syntax", e3.ColorMix = "color-mix", e3.ColorMixVariadic = "color-mix-variadic", e3.ContrastColor = "contrast-color", e3.RelativeAlphaSyntax = "relative-alpha-syntax", e3.Experimental = "experimental";
    }(me || (me = {}));
    pe = /* @__PURE__ */ new Set([he.A98_RGB, he.Display_P3, he.Linear_Display_P3, he.HEX, he.Linear_sRGB, he.ProPhoto_RGB, he.RGB, he.sRGB, he.Rec2020, he.XYZ_D50, he.XYZ_D65]);
    Ne = /[A-Z]/g;
    be = /* @__PURE__ */ new Set(["srgb", "srgb-linear", "display-p3", "display-p3-linear", "a98-rgb", "prophoto-rgb", "rec2020", "xyz", "xyz-d50", "xyz-d65"]);
    ve = /* @__PURE__ */ new Set(["srgb", "srgb-linear", "display-p3", "display-p3-linear", "a98-rgb", "prophoto-rgb", "rec2020", "lab", "oklab", "xyz", "xyz-d50", "xyz-d65"]);
    ge = /* @__PURE__ */ new Set(["hsl", "hwb", "lch", "oklch"]);
    fe = /* @__PURE__ */ new Set(["shorter", "longer", "increasing", "decreasing"]);
    de = /* @__PURE__ */ new Map();
    for (const [e3, a3] of Object.entries(d2)) de.set(e3, a3);
  }
});

// node_modules/@asamuzakjp/css-color/dist/cjs/index.cjs
var __defProp2 = Object.defineProperty;
var __getOwnPropDesc2 = Object.getOwnPropertyDescriptor;
var __getOwnPropNames2 = Object.getOwnPropertyNames;
var __hasOwnProp2 = Object.prototype.hasOwnProperty;
var __export2 = (target, all) => {
  for (var name in all)
    __defProp2(target, name, { get: all[name], enumerable: true });
};
var __copyProps2 = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames2(from))
      if (!__hasOwnProp2.call(to, key) && key !== except)
        __defProp2(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc2(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS2 = (mod2) => __copyProps2(__defProp2({}, "__esModule", { value: true }), mod2);
var index_exports = {};
__export2(index_exports, {
  convert: () => convert,
  resolve: () => resolve,
  utils: () => utils
});
module.exports = __toCommonJS2(index_exports);
var import_css_calc4 = (init_dist3(), __toCommonJS(dist_exports3));
var import_css_tokenizer4 = (init_dist(), __toCommonJS(dist_exports));
var import_lru_cache = require_index_min();
var import_css_tokenizer32 = (init_dist(), __toCommonJS(dist_exports));
var isString = (o3) => typeof o3 === "string" || o3 instanceof String;
var isStringOrNumber = (o3) => isString(o3) || typeof o3 === "number";
var _DIGIT = "(?:0|[1-9]\\d*)";
var _COMPARE = "clamp|max|min";
var _EXPO = "exp|hypot|log|pow|sqrt";
var _SIGN = "abs|sign";
var _STEP = "mod|rem|round";
var _TRIG = "a?(?:cos|sin|tan)|atan2";
var _MATH = `${_COMPARE}|${_EXPO}|${_SIGN}|${_STEP}|${_TRIG}`;
var _CALC = `calc|${_MATH}`;
var _VAR = `var|${_CALC}`;
var ANGLE = "deg|g?rad|turn";
var LENGTH = "[cm]m|[dls]?v(?:[bhiw]|max|min)|in|p[ctx]|q|r?(?:[cl]h|cap|e[mx]|ic)";
var NUM = `[+-]?(?:${_DIGIT}(?:\\.\\d*)?|\\.\\d+)(?:e-?${_DIGIT})?`;
var NUM_POSITIVE = `\\+?(?:${_DIGIT}(?:\\.\\d*)?|\\.\\d+)(?:e-?${_DIGIT})?`;
var NONE = "none";
var PCT = `${NUM}%`;
var SYN_FN_CALC = `^(?:${_CALC})\\(|(?<=[*\\/\\s\\(])(?:${_CALC})\\(`;
var SYN_FN_MATH_START = `^(?:${_MATH})\\($`;
var SYN_FN_VAR = "^var\\(|(?<=[*\\/\\s\\(])var\\(";
var SYN_FN_VAR_START = `^(?:${_VAR})\\(`;
var _ALPHA = `(?:\\s*\\/\\s*(?:${NUM}|${PCT}|${NONE}))?`;
var _ALPHA_LV3 = `(?:\\s*,\\s*(?:${NUM}|${PCT}))?`;
var _COLOR_FUNC = "(?:ok)?l(?:ab|ch)|color|hsla?|hwb|rgba?";
var _COLOR_KEY = "[a-z]+|#[\\da-f]{3}|#[\\da-f]{4}|#[\\da-f]{6}|#[\\da-f]{8}";
var _CS_HUE = "(?:ok)?lch|hsl|hwb";
var _CS_HUE_ARC = "(?:de|in)creasing|longer|shorter";
var _NUM_ANGLE = `${NUM}(?:${ANGLE})?`;
var _NUM_ANGLE_NONE = `(?:${NUM}(?:${ANGLE})?|${NONE})`;
var _NUM_PCT_NONE = `(?:${NUM}|${PCT}|${NONE})`;
var CS_HUE = `(?:${_CS_HUE})(?:\\s(?:${_CS_HUE_ARC})\\shue)?`;
var CS_HUE_CAPT = `(${_CS_HUE})(?:\\s(${_CS_HUE_ARC})\\shue)?`;
var CS_LAB = "(?:ok)?lab";
var CS_LCH = "(?:ok)?lch";
var CS_SRGB = "srgb(?:-linear)?";
var CS_RGB = `(?:a98|prophoto)-rgb|display-p3|rec2020|${CS_SRGB}`;
var CS_XYZ = "xyz(?:-d(?:50|65))?";
var CS_RECT = `${CS_LAB}|${CS_RGB}|${CS_XYZ}`;
var CS_MIX = `${CS_HUE}|${CS_RECT}`;
var FN_COLOR = "color(";
var FN_LIGHT_DARK = "light-dark(";
var FN_MIX = "color-mix(";
var FN_REL = `(?:${_COLOR_FUNC})\\(\\s*from\\s+`;
var FN_REL_CAPT = `(${_COLOR_FUNC})\\(\\s*from\\s+`;
var FN_VAR = "var(";
var SYN_FN_COLOR = `(?:${CS_RGB}|${CS_XYZ})(?:\\s+${_NUM_PCT_NONE}){3}${_ALPHA}`;
var SYN_FN_LIGHT_DARK = "^light-dark\\(";
var SYN_FN_REL = `^${FN_REL}|(?<=[\\s])${FN_REL}`;
var SYN_HSL = `${_NUM_ANGLE_NONE}(?:\\s+${_NUM_PCT_NONE}){2}${_ALPHA}`;
var SYN_HSL_LV3 = `${_NUM_ANGLE}(?:\\s*,\\s*${PCT}){2}${_ALPHA_LV3}`;
var SYN_LCH = `(?:${_NUM_PCT_NONE}\\s+){2}${_NUM_ANGLE_NONE}${_ALPHA}`;
var SYN_MOD = `${_NUM_PCT_NONE}(?:\\s+${_NUM_PCT_NONE}){2}${_ALPHA}`;
var SYN_RGB_LV3 = `(?:${NUM}(?:\\s*,\\s*${NUM}){2}|${PCT}(?:\\s*,\\s*${PCT}){2})${_ALPHA_LV3}`;
var SYN_COLOR_TYPE = `${_COLOR_KEY}|hsla?\\(\\s*${SYN_HSL_LV3}\\s*\\)|rgba?\\(\\s*${SYN_RGB_LV3}\\s*\\)|(?:hsla?|hwb)\\(\\s*${SYN_HSL}\\s*\\)|(?:(?:ok)?lab|rgba?)\\(\\s*${SYN_MOD}\\s*\\)|(?:ok)?lch\\(\\s*${SYN_LCH}\\s*\\)|color\\(\\s*${SYN_FN_COLOR}\\s*\\)`;
var SYN_MIX_PART = `(?:${SYN_COLOR_TYPE})(?:\\s+${PCT})?`;
var SYN_MIX = `color-mix\\(\\s*in\\s+(?:${CS_MIX})\\s*,\\s*${SYN_MIX_PART}\\s*,\\s*${SYN_MIX_PART}\\s*\\)`;
var SYN_MIX_CAPT = `color-mix\\(\\s*in\\s+(${CS_MIX})\\s*,\\s*(${SYN_MIX_PART})\\s*,\\s*(${SYN_MIX_PART})\\s*\\)`;
var VAL_COMP = "computedValue";
var VAL_MIX = "mixValue";
var VAL_SPEC = "specifiedValue";
var NAMESPACE = "color";
var PPTH = 1e-3;
var HALF = 0.5;
var DUO = 2;
var TRIA = 3;
var QUAD = 4;
var OCT = 8;
var DEC = 10;
var DOZ = 12;
var HEX = 16;
var SEXA = 60;
var DEG_HALF = 180;
var DEG = 360;
var MAX_PCT = 100;
var MAX_RGB = 255;
var POW_SQR = 2;
var POW_CUBE = 3;
var POW_LINEAR = 2.4;
var LINEAR_COEF = 12.92;
var LINEAR_OFFSET = 0.055;
var LAB_L = 116;
var LAB_A = 500;
var LAB_B = 200;
var LAB_EPSILON = 216 / 24389;
var LAB_KAPPA = 24389 / 27;
var D50 = [
  0.3457 / 0.3585,
  1,
  (1 - 0.3457 - 0.3585) / 0.3585
];
var MATRIX_D50_TO_D65 = [
  [0.955473421488075, -0.02309845494876471, 0.06325924320057072],
  [-0.0283697093338637, 1.0099953980813041, 0.021041441191917323],
  [0.012314014864481998, -0.020507649298898964, 1.330365926242124]
];
var MATRIX_D65_TO_D50 = [
  [1.0479297925449969, 0.022946870601609652, -0.05019226628920524],
  [0.02962780877005599, 0.9904344267538799, -0.017073799063418826],
  [-0.009243040646204504, 0.015055191490298152, 0.7518742814281371]
];
var MATRIX_L_RGB_TO_XYZ = [
  [506752 / 1228815, 87881 / 245763, 12673 / 70218],
  [87098 / 409605, 175762 / 245763, 12673 / 175545],
  [7918 / 409605, 87881 / 737289, 1001167 / 1053270]
];
var MATRIX_XYZ_TO_L_RGB = [
  [12831 / 3959, -329 / 214, -1974 / 3959],
  [-851781 / 878810, 1648619 / 878810, 36519 / 878810],
  [705 / 12673, -2585 / 12673, 705 / 667]
];
var MATRIX_XYZ_TO_LMS = [
  [0.819022437996703, 0.3619062600528904, -0.1288737815209879],
  [0.0329836539323885, 0.9292868615863434, 0.0361446663506424],
  [0.0481771893596242, 0.2642395317527308, 0.6335478284694309]
];
var MATRIX_LMS_TO_XYZ = [
  [1.2268798758459243, -0.5578149944602171, 0.2813910456659647],
  [-0.0405757452148008, 1.112286803280317, -0.0717110580655164],
  [-0.0763729366746601, -0.4214933324022432, 1.5869240198367816]
];
var MATRIX_OKLAB_TO_LMS = [
  [1, 0.3963377773761749, 0.2158037573099136],
  [1, -0.1055613458156586, -0.0638541728258133],
  [1, -0.0894841775298119, -1.2914855480194092]
];
var MATRIX_LMS_TO_OKLAB = [
  [0.210454268309314, 0.7936177747023054, -0.0040720430116193],
  [1.9779985324311684, -2.42859224204858, 0.450593709617411],
  [0.0259040424655478, 0.7827717124575296, -0.8086757549230774]
];
var MATRIX_P3_TO_XYZ = [
  [608311 / 1250200, 189793 / 714400, 198249 / 1000160],
  [35783 / 156275, 247089 / 357200, 198249 / 2500400],
  [0 / 1, 32229 / 714400, 5220557 / 5000800]
];
var MATRIX_REC2020_TO_XYZ = [
  [63426534 / 99577255, 20160776 / 139408157, 47086771 / 278816314],
  [26158966 / 99577255, 472592308 / 697040785, 8267143 / 139408157],
  [0 / 1, 19567812 / 697040785, 295819943 / 278816314]
];
var MATRIX_A98_TO_XYZ = [
  [573536 / 994567, 263643 / 1420810, 187206 / 994567],
  [591459 / 1989134, 6239551 / 9945670, 374412 / 4972835],
  [53769 / 1989134, 351524 / 4972835, 4929758 / 4972835]
];
var MATRIX_PROPHOTO_TO_XYZ_D50 = [
  [0.7977666449006423, 0.13518129740053308, 0.0313477341283922],
  [0.2880748288194013, 0.711835234241873, 8993693872564e-17],
  [0, 0, 0.8251046025104602]
];
var REG_COLOR = new RegExp(`^(?:${SYN_COLOR_TYPE})$`);
var REG_CS_HUE = new RegExp(`^${CS_HUE_CAPT}$`);
var REG_CS_XYZ = /^xyz(?:-d(?:50|65))?$/;
var REG_CURRENT = /^currentColor$/i;
var REG_FN_COLOR = new RegExp(`^color\\(\\s*(${SYN_FN_COLOR})\\s*\\)$`);
var REG_HSL = new RegExp(`^hsla?\\(\\s*(${SYN_HSL}|${SYN_HSL_LV3})\\s*\\)$`);
var REG_HWB = new RegExp(`^hwb\\(\\s*(${SYN_HSL})\\s*\\)$`);
var REG_LAB = new RegExp(`^lab\\(\\s*(${SYN_MOD})\\s*\\)$`);
var REG_LCH = new RegExp(`^lch\\(\\s*(${SYN_LCH})\\s*\\)$`);
var REG_MIX = new RegExp(`^${SYN_MIX}$`);
var REG_MIX_CAPT = new RegExp(`^${SYN_MIX_CAPT}$`);
var REG_MIX_NEST = new RegExp(`${SYN_MIX}`, "g");
var REG_OKLAB = new RegExp(`^oklab\\(\\s*(${SYN_MOD})\\s*\\)$`);
var REG_OKLCH = new RegExp(`^oklch\\(\\s*(${SYN_LCH})\\s*\\)$`);
var REG_SPEC = /^(?:specifi|comput)edValue$/;
var NAMED_COLORS = {
  aliceblue: [240, 248, 255],
  antiquewhite: [250, 235, 215],
  aqua: [0, 255, 255],
  aquamarine: [127, 255, 212],
  azure: [240, 255, 255],
  beige: [245, 245, 220],
  bisque: [255, 228, 196],
  black: [0, 0, 0],
  blanchedalmond: [255, 235, 205],
  blue: [0, 0, 255],
  blueviolet: [138, 43, 226],
  brown: [165, 42, 42],
  burlywood: [222, 184, 135],
  cadetblue: [95, 158, 160],
  chartreuse: [127, 255, 0],
  chocolate: [210, 105, 30],
  coral: [255, 127, 80],
  cornflowerblue: [100, 149, 237],
  cornsilk: [255, 248, 220],
  crimson: [220, 20, 60],
  cyan: [0, 255, 255],
  darkblue: [0, 0, 139],
  darkcyan: [0, 139, 139],
  darkgoldenrod: [184, 134, 11],
  darkgray: [169, 169, 169],
  darkgreen: [0, 100, 0],
  darkgrey: [169, 169, 169],
  darkkhaki: [189, 183, 107],
  darkmagenta: [139, 0, 139],
  darkolivegreen: [85, 107, 47],
  darkorange: [255, 140, 0],
  darkorchid: [153, 50, 204],
  darkred: [139, 0, 0],
  darksalmon: [233, 150, 122],
  darkseagreen: [143, 188, 143],
  darkslateblue: [72, 61, 139],
  darkslategray: [47, 79, 79],
  darkslategrey: [47, 79, 79],
  darkturquoise: [0, 206, 209],
  darkviolet: [148, 0, 211],
  deeppink: [255, 20, 147],
  deepskyblue: [0, 191, 255],
  dimgray: [105, 105, 105],
  dimgrey: [105, 105, 105],
  dodgerblue: [30, 144, 255],
  firebrick: [178, 34, 34],
  floralwhite: [255, 250, 240],
  forestgreen: [34, 139, 34],
  fuchsia: [255, 0, 255],
  gainsboro: [220, 220, 220],
  ghostwhite: [248, 248, 255],
  gold: [255, 215, 0],
  goldenrod: [218, 165, 32],
  gray: [128, 128, 128],
  green: [0, 128, 0],
  greenyellow: [173, 255, 47],
  grey: [128, 128, 128],
  honeydew: [240, 255, 240],
  hotpink: [255, 105, 180],
  indianred: [205, 92, 92],
  indigo: [75, 0, 130],
  ivory: [255, 255, 240],
  khaki: [240, 230, 140],
  lavender: [230, 230, 250],
  lavenderblush: [255, 240, 245],
  lawngreen: [124, 252, 0],
  lemonchiffon: [255, 250, 205],
  lightblue: [173, 216, 230],
  lightcoral: [240, 128, 128],
  lightcyan: [224, 255, 255],
  lightgoldenrodyellow: [250, 250, 210],
  lightgray: [211, 211, 211],
  lightgreen: [144, 238, 144],
  lightgrey: [211, 211, 211],
  lightpink: [255, 182, 193],
  lightsalmon: [255, 160, 122],
  lightseagreen: [32, 178, 170],
  lightskyblue: [135, 206, 250],
  lightslategray: [119, 136, 153],
  lightslategrey: [119, 136, 153],
  lightsteelblue: [176, 196, 222],
  lightyellow: [255, 255, 224],
  lime: [0, 255, 0],
  limegreen: [50, 205, 50],
  linen: [250, 240, 230],
  magenta: [255, 0, 255],
  maroon: [128, 0, 0],
  mediumaquamarine: [102, 205, 170],
  mediumblue: [0, 0, 205],
  mediumorchid: [186, 85, 211],
  mediumpurple: [147, 112, 219],
  mediumseagreen: [60, 179, 113],
  mediumslateblue: [123, 104, 238],
  mediumspringgreen: [0, 250, 154],
  mediumturquoise: [72, 209, 204],
  mediumvioletred: [199, 21, 133],
  midnightblue: [25, 25, 112],
  mintcream: [245, 255, 250],
  mistyrose: [255, 228, 225],
  moccasin: [255, 228, 181],
  navajowhite: [255, 222, 173],
  navy: [0, 0, 128],
  oldlace: [253, 245, 230],
  olive: [128, 128, 0],
  olivedrab: [107, 142, 35],
  orange: [255, 165, 0],
  orangered: [255, 69, 0],
  orchid: [218, 112, 214],
  palegoldenrod: [238, 232, 170],
  palegreen: [152, 251, 152],
  paleturquoise: [175, 238, 238],
  palevioletred: [219, 112, 147],
  papayawhip: [255, 239, 213],
  peachpuff: [255, 218, 185],
  peru: [205, 133, 63],
  pink: [255, 192, 203],
  plum: [221, 160, 221],
  powderblue: [176, 224, 230],
  purple: [128, 0, 128],
  rebeccapurple: [102, 51, 153],
  red: [255, 0, 0],
  rosybrown: [188, 143, 143],
  royalblue: [65, 105, 225],
  saddlebrown: [139, 69, 19],
  salmon: [250, 128, 114],
  sandybrown: [244, 164, 96],
  seagreen: [46, 139, 87],
  seashell: [255, 245, 238],
  sienna: [160, 82, 45],
  silver: [192, 192, 192],
  skyblue: [135, 206, 235],
  slateblue: [106, 90, 205],
  slategray: [112, 128, 144],
  slategrey: [112, 128, 144],
  snow: [255, 250, 250],
  springgreen: [0, 255, 127],
  steelblue: [70, 130, 180],
  tan: [210, 180, 140],
  teal: [0, 128, 128],
  thistle: [216, 191, 216],
  tomato: [255, 99, 71],
  turquoise: [64, 224, 208],
  violet: [238, 130, 238],
  wheat: [245, 222, 179],
  white: [255, 255, 255],
  whitesmoke: [245, 245, 245],
  yellow: [255, 255, 0],
  yellowgreen: [154, 205, 50]
};
var cacheInvalidColorValue = (cacheKey, format, nullable = false) => {
  if (format === VAL_SPEC) {
    const res2 = "";
    setCache(cacheKey, res2);
    return res2;
  }
  if (nullable) {
    setCache(cacheKey, null);
    return new NullObject();
  }
  const res = ["rgb", 0, 0, 0, 0];
  setCache(cacheKey, res);
  return res;
};
var resolveInvalidColorValue = (format, nullable = false) => {
  switch (format) {
    case "hsl":
    case "hwb":
    case VAL_MIX: {
      return new NullObject();
    }
    case VAL_SPEC: {
      return "";
    }
    default: {
      if (nullable) {
        return new NullObject();
      }
      return ["rgb", 0, 0, 0, 0];
    }
  }
};
var validateColorComponents = (arr, opt = {}) => {
  if (!Array.isArray(arr)) {
    throw new TypeError(`${arr} is not an array.`);
  }
  const {
    alpha: alpha2 = false,
    minLength = TRIA,
    maxLength = QUAD,
    minRange = 0,
    maxRange = 1,
    validateRange = true
  } = opt;
  if (!Number.isFinite(minLength)) {
    throw new TypeError(`${minLength} is not a number.`);
  }
  if (!Number.isFinite(maxLength)) {
    throw new TypeError(`${maxLength} is not a number.`);
  }
  if (!Number.isFinite(minRange)) {
    throw new TypeError(`${minRange} is not a number.`);
  }
  if (!Number.isFinite(maxRange)) {
    throw new TypeError(`${maxRange} is not a number.`);
  }
  const l2 = arr.length;
  if (l2 < minLength || l2 > maxLength) {
    throw new Error(`Unexpected array length ${l2}.`);
  }
  let i3 = 0;
  while (i3 < l2) {
    const v = arr[i3];
    if (!Number.isFinite(v)) {
      throw new TypeError(`${v} is not a number.`);
    } else if (i3 < TRIA && validateRange && (v < minRange || v > maxRange)) {
      throw new RangeError(`${v} is not between ${minRange} and ${maxRange}.`);
    } else if (i3 === TRIA && (v < 0 || v > 1)) {
      throw new RangeError(`${v} is not between 0 and 1.`);
    }
    i3++;
  }
  if (alpha2 && l2 === TRIA) {
    arr.push(1);
  }
  return arr;
};
var transformMatrix = (mtx, vct, skip = false) => {
  if (!Array.isArray(mtx)) {
    throw new TypeError(`${mtx} is not an array.`);
  } else if (mtx.length !== TRIA) {
    throw new Error(`Unexpected array length ${mtx.length}.`);
  } else if (!skip) {
    for (let i3 of mtx) {
      i3 = validateColorComponents(i3, {
        maxLength: TRIA,
        validateRange: false
      });
    }
  }
  const [[r1c1, r1c2, r1c3], [r2c1, r2c2, r2c3], [r3c1, r3c2, r3c3]] = mtx;
  let v1, v2, v3;
  if (skip) {
    [v1, v2, v3] = vct;
  } else {
    [v1, v2, v3] = validateColorComponents(vct, {
      maxLength: TRIA,
      validateRange: false
    });
  }
  const p1 = r1c1 * v1 + r1c2 * v2 + r1c3 * v3;
  const p2 = r2c1 * v1 + r2c2 * v2 + r2c3 * v3;
  const p3 = r3c1 * v1 + r3c2 * v2 + r3c3 * v3;
  return [p1, p2, p3];
};
var normalizeColorComponents = (colorA, colorB, skip = false) => {
  if (!Array.isArray(colorA)) {
    throw new TypeError(`${colorA} is not an array.`);
  } else if (colorA.length !== QUAD) {
    throw new Error(`Unexpected array length ${colorA.length}.`);
  }
  if (!Array.isArray(colorB)) {
    throw new TypeError(`${colorB} is not an array.`);
  } else if (colorB.length !== QUAD) {
    throw new Error(`Unexpected array length ${colorB.length}.`);
  }
  let i3 = 0;
  while (i3 < QUAD) {
    if (colorA[i3] === NONE && colorB[i3] === NONE) {
      colorA[i3] = 0;
      colorB[i3] = 0;
    } else if (colorA[i3] === NONE) {
      colorA[i3] = colorB[i3];
    } else if (colorB[i3] === NONE) {
      colorB[i3] = colorA[i3];
    }
    i3++;
  }
  if (skip) {
    return [colorA, colorB];
  }
  const validatedColorA = validateColorComponents(colorA, {
    minLength: QUAD,
    validateRange: false
  });
  const validatedColorB = validateColorComponents(colorB, {
    minLength: QUAD,
    validateRange: false
  });
  return [validatedColorA, validatedColorB];
};
var numberToHexString = (value) => {
  if (!Number.isFinite(value)) {
    throw new TypeError(`${value} is not a number.`);
  } else {
    value = Math.round(value);
    if (value < 0 || value > MAX_RGB) {
      throw new RangeError(`${value} is not between 0 and ${MAX_RGB}.`);
    }
  }
  let hex2 = value.toString(HEX);
  if (hex2.length === 1) {
    hex2 = `0${hex2}`;
  }
  return hex2;
};
var angleToDeg = (angle) => {
  if (isString(angle)) {
    angle = angle.trim();
  } else {
    throw new TypeError(`${angle} is not a string.`);
  }
  const GRAD = DEG / 400;
  const RAD = DEG / (Math.PI * DUO);
  const reg = new RegExp(`^(${NUM})(${ANGLE})?$`);
  if (!reg.test(angle)) {
    throw new SyntaxError(`Invalid property value: ${angle}`);
  }
  const [, value, unit] = angle.match(reg);
  let deg;
  switch (unit) {
    case "grad":
      deg = parseFloat(value) * GRAD;
      break;
    case "rad":
      deg = parseFloat(value) * RAD;
      break;
    case "turn":
      deg = parseFloat(value) * DEG;
      break;
    default:
      deg = parseFloat(value);
  }
  deg %= DEG;
  if (deg < 0) {
    deg += DEG;
  } else if (Object.is(deg, -0)) {
    deg = 0;
  }
  return deg;
};
var parseAlpha = (alpha2 = "") => {
  if (isString(alpha2)) {
    alpha2 = alpha2.trim();
    if (!alpha2) {
      alpha2 = "1";
    } else if (alpha2 === NONE) {
      alpha2 = "0";
    } else {
      let a3;
      if (alpha2.endsWith("%")) {
        a3 = parseFloat(alpha2) / MAX_PCT;
      } else {
        a3 = parseFloat(alpha2);
      }
      if (!Number.isFinite(a3)) {
        throw new TypeError(`${a3} is not a finite number.`);
      }
      if (a3 < PPTH) {
        alpha2 = "0";
      } else if (a3 > 1) {
        alpha2 = "1";
      } else {
        alpha2 = a3.toFixed(TRIA);
      }
    }
  } else {
    alpha2 = "1";
  }
  return parseFloat(alpha2);
};
var parseHexAlpha = (value) => {
  if (isString(value)) {
    if (value === "") {
      throw new SyntaxError("Invalid property value: (empty string)");
    }
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  let alpha2 = parseInt(value, HEX);
  if (alpha2 <= 0) {
    return 0;
  }
  if (alpha2 >= MAX_RGB) {
    return 1;
  }
  const alphaMap = /* @__PURE__ */ new Map();
  for (let i3 = 1; i3 < MAX_PCT; i3++) {
    alphaMap.set(Math.round(i3 * MAX_RGB / MAX_PCT), i3);
  }
  if (alphaMap.has(alpha2)) {
    alpha2 = alphaMap.get(alpha2) / MAX_PCT;
  } else {
    alpha2 = Math.round(alpha2 / MAX_RGB / PPTH) * PPTH;
  }
  return parseFloat(alpha2.toFixed(TRIA));
};
var transformRgbToLinearRgb = (rgb2, skip = false) => {
  let rr, gg, bb;
  if (skip) {
    [rr, gg, bb] = rgb2;
  } else {
    [rr, gg, bb] = validateColorComponents(rgb2, {
      maxLength: TRIA,
      maxRange: MAX_RGB
    });
  }
  let r3 = rr / MAX_RGB;
  let g2 = gg / MAX_RGB;
  let b2 = bb / MAX_RGB;
  const COND_POW = 0.04045;
  if (r3 > COND_POW) {
    r3 = Math.pow((r3 + LINEAR_OFFSET) / (1 + LINEAR_OFFSET), POW_LINEAR);
  } else {
    r3 /= LINEAR_COEF;
  }
  if (g2 > COND_POW) {
    g2 = Math.pow((g2 + LINEAR_OFFSET) / (1 + LINEAR_OFFSET), POW_LINEAR);
  } else {
    g2 /= LINEAR_COEF;
  }
  if (b2 > COND_POW) {
    b2 = Math.pow((b2 + LINEAR_OFFSET) / (1 + LINEAR_OFFSET), POW_LINEAR);
  } else {
    b2 /= LINEAR_COEF;
  }
  return [r3, g2, b2];
};
var transformRgbToXyz = (rgb2, skip = false) => {
  if (!skip) {
    rgb2 = validateColorComponents(rgb2, {
      maxLength: TRIA,
      maxRange: MAX_RGB
    });
  }
  rgb2 = transformRgbToLinearRgb(rgb2, true);
  const xyz = transformMatrix(MATRIX_L_RGB_TO_XYZ, rgb2, true);
  return xyz;
};
var transformLinearRgbToRgb = (rgb2, round2 = false) => {
  let [r3, g2, b2] = validateColorComponents(rgb2, {
    maxLength: TRIA
  });
  const COND_POW = 809 / 258400;
  if (r3 > COND_POW) {
    r3 = Math.pow(r3, 1 / POW_LINEAR) * (1 + LINEAR_OFFSET) - LINEAR_OFFSET;
  } else {
    r3 *= LINEAR_COEF;
  }
  r3 *= MAX_RGB;
  if (g2 > COND_POW) {
    g2 = Math.pow(g2, 1 / POW_LINEAR) * (1 + LINEAR_OFFSET) - LINEAR_OFFSET;
  } else {
    g2 *= LINEAR_COEF;
  }
  g2 *= MAX_RGB;
  if (b2 > COND_POW) {
    b2 = Math.pow(b2, 1 / POW_LINEAR) * (1 + LINEAR_OFFSET) - LINEAR_OFFSET;
  } else {
    b2 *= LINEAR_COEF;
  }
  b2 *= MAX_RGB;
  return [
    round2 ? Math.round(r3) : r3,
    round2 ? Math.round(g2) : g2,
    round2 ? Math.round(b2) : b2
  ];
};
var transformXyzToRgb = (xyz, skip = false) => {
  if (!skip) {
    xyz = validateColorComponents(xyz, {
      maxLength: TRIA,
      validateRange: false
    });
  }
  let [r3, g2, b2] = transformMatrix(MATRIX_XYZ_TO_L_RGB, xyz, true);
  [r3, g2, b2] = transformLinearRgbToRgb(
    [
      Math.min(Math.max(r3, 0), 1),
      Math.min(Math.max(g2, 0), 1),
      Math.min(Math.max(b2, 0), 1)
    ],
    true
  );
  return [r3, g2, b2];
};
var transformXyzToHsl = (xyz, skip = false) => {
  const [rr, gg, bb] = transformXyzToRgb(xyz, skip);
  const r3 = rr / MAX_RGB;
  const g2 = gg / MAX_RGB;
  const b2 = bb / MAX_RGB;
  const max2 = Math.max(r3, g2, b2);
  const min2 = Math.min(r3, g2, b2);
  const d3 = max2 - min2;
  const l2 = (max2 + min2) * HALF * MAX_PCT;
  let h2, s3;
  if (Math.round(l2) === 0 || Math.round(l2) === MAX_PCT) {
    h2 = 0;
    s3 = 0;
  } else {
    s3 = d3 / (1 - Math.abs(max2 + min2 - 1)) * MAX_PCT;
    if (s3 === 0) {
      h2 = 0;
    } else {
      switch (max2) {
        case r3:
          h2 = (g2 - b2) / d3;
          break;
        case g2:
          h2 = (b2 - r3) / d3 + DUO;
          break;
        case b2:
        default:
          h2 = (r3 - g2) / d3 + QUAD;
          break;
      }
      h2 = h2 * SEXA % DEG;
      if (h2 < 0) {
        h2 += DEG;
      }
    }
  }
  return [h2, s3, l2];
};
var transformXyzToHwb = (xyz, skip = false) => {
  const [r3, g2, b2] = transformXyzToRgb(xyz, skip);
  const wh = Math.min(r3, g2, b2) / MAX_RGB;
  const bk = 1 - Math.max(r3, g2, b2) / MAX_RGB;
  let h2;
  if (wh + bk === 1) {
    h2 = 0;
  } else {
    [h2] = transformXyzToHsl(xyz);
  }
  return [h2, wh * MAX_PCT, bk * MAX_PCT];
};
var transformXyzToOklab = (xyz, skip = false) => {
  if (!skip) {
    xyz = validateColorComponents(xyz, {
      maxLength: TRIA,
      validateRange: false
    });
  }
  const lms = transformMatrix(MATRIX_XYZ_TO_LMS, xyz, true);
  const xyzLms = lms.map((c3) => Math.cbrt(c3));
  let [l2, a3, b2] = transformMatrix(MATRIX_LMS_TO_OKLAB, xyzLms, true);
  l2 = Math.min(Math.max(l2, 0), 1);
  const lPct = Math.round(parseFloat(l2.toFixed(QUAD)) * MAX_PCT);
  if (lPct === 0 || lPct === MAX_PCT) {
    a3 = 0;
    b2 = 0;
  }
  return [l2, a3, b2];
};
var transformXyzToOklch = (xyz, skip = false) => {
  const [l2, a3, b2] = transformXyzToOklab(xyz, skip);
  let c3, h2;
  const lPct = Math.round(parseFloat(l2.toFixed(QUAD)) * MAX_PCT);
  if (lPct === 0 || lPct === MAX_PCT) {
    c3 = 0;
    h2 = 0;
  } else {
    c3 = Math.max(Math.sqrt(Math.pow(a3, POW_SQR) + Math.pow(b2, POW_SQR)), 0);
    if (parseFloat(c3.toFixed(QUAD)) === 0) {
      h2 = 0;
    } else {
      h2 = Math.atan2(b2, a3) * DEG_HALF / Math.PI;
      if (h2 < 0) {
        h2 += DEG;
      }
    }
  }
  return [l2, c3, h2];
};
var transformXyzD50ToRgb = (xyz, skip = false) => {
  if (!skip) {
    xyz = validateColorComponents(xyz, {
      maxLength: TRIA,
      validateRange: false
    });
  }
  const xyzD65 = transformMatrix(MATRIX_D50_TO_D65, xyz, true);
  const rgb2 = transformXyzToRgb(xyzD65, true);
  return rgb2;
};
var transformXyzD50ToLab = (xyz, skip = false) => {
  if (!skip) {
    xyz = validateColorComponents(xyz, {
      maxLength: TRIA,
      validateRange: false
    });
  }
  const xyzD50 = xyz.map((val, i3) => val / D50[i3]);
  const [f0, f1, f22] = xyzD50.map(
    (val) => val > LAB_EPSILON ? Math.cbrt(val) : (val * LAB_KAPPA + HEX) / LAB_L
  );
  const l2 = Math.min(Math.max(LAB_L * f1 - HEX, 0), MAX_PCT);
  let a3, b2;
  if (l2 === 0 || l2 === MAX_PCT) {
    a3 = 0;
    b2 = 0;
  } else {
    a3 = (f0 - f1) * LAB_A;
    b2 = (f1 - f22) * LAB_B;
  }
  return [l2, a3, b2];
};
var transformXyzD50ToLch = (xyz, skip = false) => {
  const [l2, a3, b2] = transformXyzD50ToLab(xyz, skip);
  let c3, h2;
  if (l2 === 0 || l2 === MAX_PCT) {
    c3 = 0;
    h2 = 0;
  } else {
    c3 = Math.max(Math.sqrt(Math.pow(a3, POW_SQR) + Math.pow(b2, POW_SQR)), 0);
    h2 = Math.atan2(b2, a3) * DEG_HALF / Math.PI;
    if (h2 < 0) {
      h2 += DEG;
    }
  }
  return [l2, c3, h2];
};
var convertRgbToHex = (rgb2) => {
  const [r3, g2, b2, alpha2] = validateColorComponents(rgb2, {
    alpha: true,
    maxRange: MAX_RGB
  });
  const rr = numberToHexString(r3);
  const gg = numberToHexString(g2);
  const bb = numberToHexString(b2);
  const aa = numberToHexString(alpha2 * MAX_RGB);
  let hex2;
  if (aa === "ff") {
    hex2 = `#${rr}${gg}${bb}`;
  } else {
    hex2 = `#${rr}${gg}${bb}${aa}`;
  }
  return hex2;
};
var convertHexToRgb = (value) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  if (!(/^#[\da-f]{6}$/.test(value) || /^#[\da-f]{3}$/.test(value) || /^#[\da-f]{8}$/.test(value) || /^#[\da-f]{4}$/.test(value))) {
    throw new SyntaxError(`Invalid property value: ${value}`);
  }
  const arr = [];
  if (/^#[\da-f]{3}$/.test(value)) {
    const [, r3, g2, b2] = value.match(
      /^#([\da-f])([\da-f])([\da-f])$/
    );
    arr.push(
      parseInt(`${r3}${r3}`, HEX),
      parseInt(`${g2}${g2}`, HEX),
      parseInt(`${b2}${b2}`, HEX),
      1
    );
  } else if (/^#[\da-f]{4}$/.test(value)) {
    const [, r3, g2, b2, alpha2] = value.match(
      /^#([\da-f])([\da-f])([\da-f])([\da-f])$/
    );
    arr.push(
      parseInt(`${r3}${r3}`, HEX),
      parseInt(`${g2}${g2}`, HEX),
      parseInt(`${b2}${b2}`, HEX),
      parseHexAlpha(`${alpha2}${alpha2}`)
    );
  } else if (/^#[\da-f]{8}$/.test(value)) {
    const [, r3, g2, b2, alpha2] = value.match(
      /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})([\da-f]{2})$/
    );
    arr.push(
      parseInt(r3, HEX),
      parseInt(g2, HEX),
      parseInt(b2, HEX),
      parseHexAlpha(alpha2)
    );
  } else {
    const [, r3, g2, b2] = value.match(
      /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/
    );
    arr.push(parseInt(r3, HEX), parseInt(g2, HEX), parseInt(b2, HEX), 1);
  }
  return arr;
};
var convertHexToLinearRgb = (value) => {
  const [rr, gg, bb, alpha2] = convertHexToRgb(value);
  const [r3, g2, b2] = transformRgbToLinearRgb([rr, gg, bb], true);
  return [r3, g2, b2, alpha2];
};
var convertHexToXyz = (value) => {
  const [r3, g2, b2, alpha2] = convertHexToLinearRgb(value);
  const [x2, y2, z2] = transformMatrix(MATRIX_L_RGB_TO_XYZ, [r3, g2, b2], true);
  return [x2, y2, z2, alpha2];
};
var parseRgb = (value, opt = {}) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  const reg = new RegExp(`^rgba?\\(\\s*(${SYN_MOD}|${SYN_RGB_LV3})\\s*\\)$`);
  if (!reg.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const [, val] = value.match(reg);
  const [v1, v2, v3, v4 = ""] = val.replace(/[,/]/g, " ").split(/\s+/);
  let r3, g2, b2;
  if (v1 === NONE) {
    r3 = 0;
  } else {
    if (v1.endsWith("%")) {
      r3 = parseFloat(v1) * MAX_RGB / MAX_PCT;
    } else {
      r3 = parseFloat(v1);
    }
    r3 = Math.min(Math.max(roundToPrecision(r3, OCT), 0), MAX_RGB);
  }
  if (v2 === NONE) {
    g2 = 0;
  } else {
    if (v2.endsWith("%")) {
      g2 = parseFloat(v2) * MAX_RGB / MAX_PCT;
    } else {
      g2 = parseFloat(v2);
    }
    g2 = Math.min(Math.max(roundToPrecision(g2, OCT), 0), MAX_RGB);
  }
  if (v3 === NONE) {
    b2 = 0;
  } else {
    if (v3.endsWith("%")) {
      b2 = parseFloat(v3) * MAX_RGB / MAX_PCT;
    } else {
      b2 = parseFloat(v3);
    }
    b2 = Math.min(Math.max(roundToPrecision(b2, OCT), 0), MAX_RGB);
  }
  const alpha2 = parseAlpha(v4);
  return ["rgb", r3, g2, b2, format === VAL_MIX && v4 === NONE ? NONE : alpha2];
};
var parseHsl = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  if (!REG_HSL.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const [, val] = value.match(REG_HSL);
  const [v1, v2, v3, v4 = ""] = val.replace(/[,/]/g, " ").split(/\s+/);
  let h2, s3, l2;
  if (v1 === NONE) {
    h2 = 0;
  } else {
    h2 = angleToDeg(v1);
  }
  if (v2 === NONE) {
    s3 = 0;
  } else {
    s3 = Math.min(Math.max(parseFloat(v2), 0), MAX_PCT);
  }
  if (v3 === NONE) {
    l2 = 0;
  } else {
    l2 = Math.min(Math.max(parseFloat(v3), 0), MAX_PCT);
  }
  const alpha2 = parseAlpha(v4);
  if (format === "hsl") {
    return [
      format,
      v1 === NONE ? v1 : h2,
      v2 === NONE ? v2 : s3,
      v3 === NONE ? v3 : l2,
      v4 === NONE ? v4 : alpha2
    ];
  }
  h2 = h2 / DEG * DOZ;
  l2 /= MAX_PCT;
  const sa = s3 / MAX_PCT * Math.min(l2, 1 - l2);
  const rk = h2 % DOZ;
  const gk = (8 + h2) % DOZ;
  const bk = (4 + h2) % DOZ;
  const r3 = l2 - sa * Math.max(-1, Math.min(rk - TRIA, TRIA ** POW_SQR - rk, 1));
  const g2 = l2 - sa * Math.max(-1, Math.min(gk - TRIA, TRIA ** POW_SQR - gk, 1));
  const b2 = l2 - sa * Math.max(-1, Math.min(bk - TRIA, TRIA ** POW_SQR - bk, 1));
  return [
    "rgb",
    Math.min(Math.max(roundToPrecision(r3 * MAX_RGB, OCT), 0), MAX_RGB),
    Math.min(Math.max(roundToPrecision(g2 * MAX_RGB, OCT), 0), MAX_RGB),
    Math.min(Math.max(roundToPrecision(b2 * MAX_RGB, OCT), 0), MAX_RGB),
    alpha2
  ];
};
var parseHwb = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  if (!REG_HWB.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const [, val] = value.match(REG_HWB);
  const [v1, v2, v3, v4 = ""] = val.replace("/", " ").split(/\s+/);
  let h2, wh, bk;
  if (v1 === NONE) {
    h2 = 0;
  } else {
    h2 = angleToDeg(v1);
  }
  if (v2 === NONE) {
    wh = 0;
  } else {
    wh = Math.min(Math.max(parseFloat(v2), 0), MAX_PCT) / MAX_PCT;
  }
  if (v3 === NONE) {
    bk = 0;
  } else {
    bk = Math.min(Math.max(parseFloat(v3), 0), MAX_PCT) / MAX_PCT;
  }
  const alpha2 = parseAlpha(v4);
  if (format === "hwb") {
    return [
      format,
      v1 === NONE ? v1 : h2,
      v2 === NONE ? v2 : wh * MAX_PCT,
      v3 === NONE ? v3 : bk * MAX_PCT,
      v4 === NONE ? v4 : alpha2
    ];
  }
  if (wh + bk >= 1) {
    const v = roundToPrecision(wh / (wh + bk) * MAX_RGB, OCT);
    return ["rgb", v, v, v, alpha2];
  }
  const factor = (1 - wh - bk) / MAX_RGB;
  let [, r3, g2, b2] = parseHsl(`hsl(${h2} 100 50)`);
  r3 = roundToPrecision((r3 * factor + wh) * MAX_RGB, OCT);
  g2 = roundToPrecision((g2 * factor + wh) * MAX_RGB, OCT);
  b2 = roundToPrecision((b2 * factor + wh) * MAX_RGB, OCT);
  return [
    "rgb",
    Math.min(Math.max(r3, 0), MAX_RGB),
    Math.min(Math.max(g2, 0), MAX_RGB),
    Math.min(Math.max(b2, 0), MAX_RGB),
    alpha2
  ];
};
var parseLab = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  if (!REG_LAB.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const COEF_PCT = 1.25;
  const COND_POW = 8;
  const [, val] = value.match(REG_LAB);
  const [v1, v2, v3, v4 = ""] = val.replace("/", " ").split(/\s+/);
  let l2, a3, b2;
  if (v1 === NONE) {
    l2 = 0;
  } else {
    if (v1.endsWith("%")) {
      l2 = parseFloat(v1);
      if (l2 > MAX_PCT) {
        l2 = MAX_PCT;
      }
    } else {
      l2 = parseFloat(v1);
    }
    if (l2 < 0) {
      l2 = 0;
    }
  }
  if (v2 === NONE) {
    a3 = 0;
  } else {
    a3 = v2.endsWith("%") ? parseFloat(v2) * COEF_PCT : parseFloat(v2);
  }
  if (v3 === NONE) {
    b2 = 0;
  } else {
    b2 = v3.endsWith("%") ? parseFloat(v3) * COEF_PCT : parseFloat(v3);
  }
  const alpha2 = parseAlpha(v4);
  if (REG_SPEC.test(format)) {
    return [
      "lab",
      v1 === NONE ? v1 : roundToPrecision(l2, HEX),
      v2 === NONE ? v2 : roundToPrecision(a3, HEX),
      v3 === NONE ? v3 : roundToPrecision(b2, HEX),
      v4 === NONE ? v4 : alpha2
    ];
  }
  const fl = (l2 + HEX) / LAB_L;
  const fa = a3 / LAB_A + fl;
  const fb = fl - b2 / LAB_B;
  const powFl = Math.pow(fl, POW_CUBE);
  const powFa = Math.pow(fa, POW_CUBE);
  const powFb = Math.pow(fb, POW_CUBE);
  const xyz = [
    powFa > LAB_EPSILON ? powFa : (fa * LAB_L - HEX) / LAB_KAPPA,
    l2 > COND_POW ? powFl : l2 / LAB_KAPPA,
    powFb > LAB_EPSILON ? powFb : (fb * LAB_L - HEX) / LAB_KAPPA
  ];
  const [x2, y2, z2] = xyz.map(
    (val2, i3) => val2 * D50[i3]
  );
  return [
    "xyz-d50",
    roundToPrecision(x2, HEX),
    roundToPrecision(y2, HEX),
    roundToPrecision(z2, HEX),
    alpha2
  ];
};
var parseLch = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  if (!REG_LCH.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const COEF_PCT = 1.5;
  const [, val] = value.match(REG_LCH);
  const [v1, v2, v3, v4 = ""] = val.replace("/", " ").split(/\s+/);
  let l2, c3, h2;
  if (v1 === NONE) {
    l2 = 0;
  } else {
    l2 = parseFloat(v1);
    if (l2 < 0) {
      l2 = 0;
    }
  }
  if (v2 === NONE) {
    c3 = 0;
  } else {
    c3 = v2.endsWith("%") ? parseFloat(v2) * COEF_PCT : parseFloat(v2);
  }
  if (v3 === NONE) {
    h2 = 0;
  } else {
    h2 = angleToDeg(v3);
  }
  const alpha2 = parseAlpha(v4);
  if (REG_SPEC.test(format)) {
    return [
      "lch",
      v1 === NONE ? v1 : roundToPrecision(l2, HEX),
      v2 === NONE ? v2 : roundToPrecision(c3, HEX),
      v3 === NONE ? v3 : roundToPrecision(h2, HEX),
      v4 === NONE ? v4 : alpha2
    ];
  }
  const a3 = c3 * Math.cos(h2 * Math.PI / DEG_HALF);
  const b2 = c3 * Math.sin(h2 * Math.PI / DEG_HALF);
  const [, x2, y2, z2] = parseLab(`lab(${l2} ${a3} ${b2})`);
  return [
    "xyz-d50",
    roundToPrecision(x2, HEX),
    roundToPrecision(y2, HEX),
    roundToPrecision(z2, HEX),
    alpha2
  ];
};
var parseOklab = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  if (!REG_OKLAB.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const COEF_PCT = 0.4;
  const [, val] = value.match(REG_OKLAB);
  const [v1, v2, v3, v4 = ""] = val.replace("/", " ").split(/\s+/);
  let l2, a3, b2;
  if (v1 === NONE) {
    l2 = 0;
  } else {
    l2 = v1.endsWith("%") ? parseFloat(v1) / MAX_PCT : parseFloat(v1);
    if (l2 < 0) {
      l2 = 0;
    }
  }
  if (v2 === NONE) {
    a3 = 0;
  } else if (v2.endsWith("%")) {
    a3 = parseFloat(v2) * COEF_PCT / MAX_PCT;
  } else {
    a3 = parseFloat(v2);
  }
  if (v3 === NONE) {
    b2 = 0;
  } else if (v3.endsWith("%")) {
    b2 = parseFloat(v3) * COEF_PCT / MAX_PCT;
  } else {
    b2 = parseFloat(v3);
  }
  const alpha2 = parseAlpha(v4);
  if (REG_SPEC.test(format)) {
    return [
      "oklab",
      v1 === NONE ? v1 : roundToPrecision(l2, HEX),
      v2 === NONE ? v2 : roundToPrecision(a3, HEX),
      v3 === NONE ? v3 : roundToPrecision(b2, HEX),
      v4 === NONE ? v4 : alpha2
    ];
  }
  const lms = transformMatrix(MATRIX_OKLAB_TO_LMS, [l2, a3, b2]);
  const xyzLms = lms.map((c3) => Math.pow(c3, POW_CUBE));
  const [x2, y2, z2] = transformMatrix(MATRIX_LMS_TO_XYZ, xyzLms, true);
  return [
    "xyz-d65",
    roundToPrecision(x2, HEX),
    roundToPrecision(y2, HEX),
    roundToPrecision(z2, HEX),
    alpha2
  ];
};
var parseOklch = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  if (!REG_OKLCH.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const COEF_PCT = 0.4;
  const [, val] = value.match(REG_OKLCH);
  const [v1, v2, v3, v4 = ""] = val.replace("/", " ").split(/\s+/);
  let l2, c3, h2;
  if (v1 === NONE) {
    l2 = 0;
  } else {
    l2 = v1.endsWith("%") ? parseFloat(v1) / MAX_PCT : parseFloat(v1);
    if (l2 < 0) {
      l2 = 0;
    }
  }
  if (v2 === NONE) {
    c3 = 0;
  } else {
    if (v2.endsWith("%")) {
      c3 = parseFloat(v2) * COEF_PCT / MAX_PCT;
    } else {
      c3 = parseFloat(v2);
    }
    if (c3 < 0) {
      c3 = 0;
    }
  }
  if (v3 === NONE) {
    h2 = 0;
  } else {
    h2 = angleToDeg(v3);
  }
  const alpha2 = parseAlpha(v4);
  if (REG_SPEC.test(format)) {
    return [
      "oklch",
      v1 === NONE ? v1 : roundToPrecision(l2, HEX),
      v2 === NONE ? v2 : roundToPrecision(c3, HEX),
      v3 === NONE ? v3 : roundToPrecision(h2, HEX),
      v4 === NONE ? v4 : alpha2
    ];
  }
  const a3 = c3 * Math.cos(h2 * Math.PI / DEG_HALF);
  const b2 = c3 * Math.sin(h2 * Math.PI / DEG_HALF);
  const lms = transformMatrix(MATRIX_OKLAB_TO_LMS, [l2, a3, b2]);
  const xyzLms = lms.map((cc) => Math.pow(cc, POW_CUBE));
  const [x2, y2, z2] = transformMatrix(MATRIX_LMS_TO_XYZ, xyzLms, true);
  return [
    "xyz-d65",
    roundToPrecision(x2, HEX),
    roundToPrecision(y2, HEX),
    roundToPrecision(z2, HEX),
    alpha2
  ];
};
var parseColorFunc = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { colorSpace = "", d50 = false, format = "", nullable = false } = opt;
  if (!REG_FN_COLOR.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  const [, val] = value.match(REG_FN_COLOR);
  let [cs, v1, v2, v3, v4 = ""] = val.replace("/", " ").split(/\s+/);
  let r3, g2, b2;
  if (cs === "xyz") {
    cs = "xyz-d65";
  }
  if (v1 === NONE) {
    r3 = 0;
  } else {
    r3 = v1.endsWith("%") ? parseFloat(v1) / MAX_PCT : parseFloat(v1);
  }
  if (v2 === NONE) {
    g2 = 0;
  } else {
    g2 = v2.endsWith("%") ? parseFloat(v2) / MAX_PCT : parseFloat(v2);
  }
  if (v3 === NONE) {
    b2 = 0;
  } else {
    b2 = v3.endsWith("%") ? parseFloat(v3) / MAX_PCT : parseFloat(v3);
  }
  const alpha2 = parseAlpha(v4);
  if (REG_SPEC.test(format) || format === VAL_MIX && cs === colorSpace) {
    return [
      cs,
      v1 === NONE ? v1 : roundToPrecision(r3, DEC),
      v2 === NONE ? v2 : roundToPrecision(g2, DEC),
      v3 === NONE ? v3 : roundToPrecision(b2, DEC),
      v4 === NONE ? v4 : alpha2
    ];
  }
  let x2 = 0;
  let y2 = 0;
  let z2 = 0;
  if (cs === "srgb-linear") {
    [x2, y2, z2] = transformMatrix(MATRIX_L_RGB_TO_XYZ, [r3, g2, b2]);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else if (cs === "display-p3") {
    const linearRgb = transformRgbToLinearRgb([
      r3 * MAX_RGB,
      g2 * MAX_RGB,
      b2 * MAX_RGB
    ]);
    [x2, y2, z2] = transformMatrix(MATRIX_P3_TO_XYZ, linearRgb);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else if (cs === "rec2020") {
    const ALPHA = 1.09929682680944;
    const BETA = 0.018053968510807;
    const REC_COEF = 0.45;
    const rgb2 = [r3, g2, b2].map((c3) => {
      let cl;
      if (c3 < BETA * REC_COEF * DEC) {
        cl = c3 / (REC_COEF * DEC);
      } else {
        cl = Math.pow((c3 + ALPHA - 1) / ALPHA, 1 / REC_COEF);
      }
      return cl;
    });
    [x2, y2, z2] = transformMatrix(MATRIX_REC2020_TO_XYZ, rgb2);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else if (cs === "a98-rgb") {
    const POW_A98 = 563 / 256;
    const rgb2 = [r3, g2, b2].map((c3) => {
      const cl = Math.pow(c3, POW_A98);
      return cl;
    });
    [x2, y2, z2] = transformMatrix(MATRIX_A98_TO_XYZ, rgb2);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else if (cs === "prophoto-rgb") {
    const POW_PROPHOTO = 1.8;
    const rgb2 = [r3, g2, b2].map((c3) => {
      let cl;
      if (c3 > 1 / (HEX * DUO)) {
        cl = Math.pow(c3, POW_PROPHOTO);
      } else {
        cl = c3 / HEX;
      }
      return cl;
    });
    [x2, y2, z2] = transformMatrix(MATRIX_PROPHOTO_TO_XYZ_D50, rgb2);
    if (!d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D50_TO_D65, [x2, y2, z2], true);
    }
  } else if (/^xyz(?:-d(?:50|65))?$/.test(cs)) {
    [x2, y2, z2] = [r3, g2, b2];
    if (cs === "xyz-d50") {
      if (!d50) {
        [x2, y2, z2] = transformMatrix(MATRIX_D50_TO_D65, [x2, y2, z2]);
      }
    } else if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else {
    [x2, y2, z2] = transformRgbToXyz([r3 * MAX_RGB, g2 * MAX_RGB, b2 * MAX_RGB]);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  }
  return [
    d50 ? "xyz-d50" : "xyz-d65",
    roundToPrecision(x2, HEX),
    roundToPrecision(y2, HEX),
    roundToPrecision(z2, HEX),
    format === VAL_MIX && v4 === NONE ? v4 : alpha2
  ];
};
var parseColorValue = (value, opt = {}) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { d50 = false, format = "", nullable = false } = opt;
  if (!REG_COLOR.test(value)) {
    const res = resolveInvalidColorValue(format, nullable);
    if (res instanceof NullObject) {
      return res;
    }
    if (isString(res)) {
      return res;
    }
    return res;
  }
  let x2 = 0;
  let y2 = 0;
  let z2 = 0;
  let alpha2 = 0;
  if (REG_CURRENT.test(value)) {
    if (format === VAL_COMP) {
      return ["rgb", 0, 0, 0, 0];
    }
    if (format === VAL_SPEC) {
      return value;
    }
  } else if (/^[a-z]+$/.test(value)) {
    if (Object.hasOwn(NAMED_COLORS, value)) {
      if (format === VAL_SPEC) {
        return value;
      }
      const [r3, g2, b2] = NAMED_COLORS[value];
      alpha2 = 1;
      if (format === VAL_COMP) {
        return ["rgb", r3, g2, b2, alpha2];
      }
      [x2, y2, z2] = transformRgbToXyz([r3, g2, b2], true);
      if (d50) {
        [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
      }
    } else {
      switch (format) {
        case VAL_COMP: {
          if (nullable && value !== "transparent") {
            return new NullObject();
          }
          return ["rgb", 0, 0, 0, 0];
        }
        case VAL_SPEC: {
          if (value === "transparent") {
            return value;
          }
          return "";
        }
        case VAL_MIX: {
          if (value === "transparent") {
            return ["rgb", 0, 0, 0, 0];
          }
          return new NullObject();
        }
        default:
      }
    }
  } else if (value[0] === "#") {
    if (REG_SPEC.test(format)) {
      const rgb2 = convertHexToRgb(value);
      return ["rgb", ...rgb2];
    }
    [x2, y2, z2, alpha2] = convertHexToXyz(value);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else if (value.startsWith("lab")) {
    if (REG_SPEC.test(format)) {
      return parseLab(value, opt);
    }
    [, x2, y2, z2, alpha2] = parseLab(value);
    if (!d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D50_TO_D65, [x2, y2, z2], true);
    }
  } else if (value.startsWith("lch")) {
    if (REG_SPEC.test(format)) {
      return parseLch(value, opt);
    }
    [, x2, y2, z2, alpha2] = parseLch(value);
    if (!d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D50_TO_D65, [x2, y2, z2], true);
    }
  } else if (value.startsWith("oklab")) {
    if (REG_SPEC.test(format)) {
      return parseOklab(value, opt);
    }
    [, x2, y2, z2, alpha2] = parseOklab(value);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else if (value.startsWith("oklch")) {
    if (REG_SPEC.test(format)) {
      return parseOklch(value, opt);
    }
    [, x2, y2, z2, alpha2] = parseOklch(value);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  } else {
    let r3, g2, b2;
    if (value.startsWith("hsl")) {
      [, r3, g2, b2, alpha2] = parseHsl(value);
    } else if (value.startsWith("hwb")) {
      [, r3, g2, b2, alpha2] = parseHwb(value);
    } else {
      [, r3, g2, b2, alpha2] = parseRgb(value, opt);
    }
    if (REG_SPEC.test(format)) {
      return ["rgb", Math.round(r3), Math.round(g2), Math.round(b2), alpha2];
    }
    [x2, y2, z2] = transformRgbToXyz([r3, g2, b2]);
    if (d50) {
      [x2, y2, z2] = transformMatrix(MATRIX_D65_TO_D50, [x2, y2, z2], true);
    }
  }
  return [
    d50 ? "xyz-d50" : "xyz-d65",
    roundToPrecision(x2, HEX),
    roundToPrecision(y2, HEX),
    roundToPrecision(z2, HEX),
    alpha2
  ];
};
var resolveColorValue = (value, opt = {}) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { colorSpace = "", format = "", nullable = false } = opt;
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE,
      name: "resolveColorValue",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    const cachedItem = cachedResult.item;
    if (isString(cachedItem)) {
      return cachedItem;
    }
    return cachedItem;
  }
  if (!REG_COLOR.test(value)) {
    const res2 = resolveInvalidColorValue(format, nullable);
    if (res2 instanceof NullObject) {
      setCache(cacheKey, null);
      return res2;
    }
    setCache(cacheKey, res2);
    if (isString(res2)) {
      return res2;
    }
    return res2;
  }
  let cs = "";
  let r3 = 0;
  let g2 = 0;
  let b2 = 0;
  let alpha2 = 0;
  if (REG_CURRENT.test(value)) {
    if (format === VAL_SPEC) {
      setCache(cacheKey, value);
      return value;
    }
  } else if (/^[a-z]+$/.test(value)) {
    if (Object.hasOwn(NAMED_COLORS, value)) {
      if (format === VAL_SPEC) {
        setCache(cacheKey, value);
        return value;
      }
      [r3, g2, b2] = NAMED_COLORS[value];
      alpha2 = 1;
    } else {
      switch (format) {
        case VAL_SPEC: {
          if (value === "transparent") {
            setCache(cacheKey, value);
            return value;
          }
          const res2 = "";
          setCache(cacheKey, res2);
          return res2;
        }
        case VAL_MIX: {
          if (value === "transparent") {
            const res2 = ["rgb", 0, 0, 0, 0];
            setCache(cacheKey, res2);
            return res2;
          }
          setCache(cacheKey, null);
          return new NullObject();
        }
        case VAL_COMP:
        default: {
          if (nullable && value !== "transparent") {
            setCache(cacheKey, null);
            return new NullObject();
          }
          const res2 = ["rgb", 0, 0, 0, 0];
          setCache(cacheKey, res2);
          return res2;
        }
      }
    }
  } else if (value[0] === "#") {
    [r3, g2, b2, alpha2] = convertHexToRgb(value);
  } else if (value.startsWith("hsl")) {
    [, r3, g2, b2, alpha2] = parseHsl(value, opt);
  } else if (value.startsWith("hwb")) {
    [, r3, g2, b2, alpha2] = parseHwb(value, opt);
  } else if (/^l(?:ab|ch)/.test(value)) {
    let x2, y2, z2;
    if (value.startsWith("lab")) {
      [cs, x2, y2, z2, alpha2] = parseLab(value, opt);
    } else {
      [cs, x2, y2, z2, alpha2] = parseLch(value, opt);
    }
    if (REG_SPEC.test(format)) {
      const res2 = [cs, x2, y2, z2, alpha2];
      setCache(cacheKey, res2);
      return res2;
    }
    [r3, g2, b2] = transformXyzD50ToRgb([x2, y2, z2]);
  } else if (/^okl(?:ab|ch)/.test(value)) {
    let x2, y2, z2;
    if (value.startsWith("oklab")) {
      [cs, x2, y2, z2, alpha2] = parseOklab(value, opt);
    } else {
      [cs, x2, y2, z2, alpha2] = parseOklch(value, opt);
    }
    if (REG_SPEC.test(format)) {
      const res2 = [cs, x2, y2, z2, alpha2];
      setCache(cacheKey, res2);
      return res2;
    }
    [r3, g2, b2] = transformXyzToRgb([x2, y2, z2]);
  } else {
    [, r3, g2, b2, alpha2] = parseRgb(value, opt);
  }
  if (format === VAL_MIX && colorSpace === "srgb") {
    const res2 = [
      "srgb",
      r3 / MAX_RGB,
      g2 / MAX_RGB,
      b2 / MAX_RGB,
      alpha2
    ];
    setCache(cacheKey, res2);
    return res2;
  }
  const res = [
    "rgb",
    Math.round(r3),
    Math.round(g2),
    Math.round(b2),
    alpha2
  ];
  setCache(cacheKey, res);
  return res;
};
var resolveColorFunc = (value, opt = {}) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { colorSpace = "", format = "", nullable = false } = opt;
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE,
      name: "resolveColorFunc",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    const cachedItem = cachedResult.item;
    if (isString(cachedItem)) {
      return cachedItem;
    }
    return cachedItem;
  }
  if (!REG_FN_COLOR.test(value)) {
    const res2 = resolveInvalidColorValue(format, nullable);
    if (res2 instanceof NullObject) {
      setCache(cacheKey, null);
      return res2;
    }
    setCache(cacheKey, res2);
    if (isString(res2)) {
      return res2;
    }
    return res2;
  }
  const [cs, v1, v2, v3, v4] = parseColorFunc(
    value,
    opt
  );
  if (REG_SPEC.test(format) || format === VAL_MIX && cs === colorSpace) {
    const res2 = [cs, v1, v2, v3, v4];
    setCache(cacheKey, res2);
    return res2;
  }
  const x2 = parseFloat(`${v1}`);
  const y2 = parseFloat(`${v2}`);
  const z2 = parseFloat(`${v3}`);
  const alpha2 = parseAlpha(`${v4}`);
  const [r3, g2, b2] = transformXyzToRgb([x2, y2, z2], true);
  const res = ["rgb", r3, g2, b2, alpha2];
  setCache(cacheKey, res);
  return res;
};
var convertColorToLinearRgb = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { colorSpace = "", format = "" } = opt;
  let cs = "";
  let r3, g2, b2, alpha2, x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [cs, x2, y2, z2, alpha2] = xyz;
    if (cs === colorSpace) {
      return [x2, y2, z2, alpha2];
    }
    [r3, g2, b2] = transformMatrix(MATRIX_XYZ_TO_L_RGB, [x2, y2, z2], true);
  } else if (value.startsWith(FN_COLOR)) {
    const [, val] = value.match(REG_FN_COLOR);
    const [cs2] = val.replace("/", " ").split(/\s+/);
    if (cs2 === "srgb-linear") {
      [, r3, g2, b2, alpha2] = resolveColorFunc(value, {
        format: VAL_COMP
      });
    } else {
      [, x2, y2, z2, alpha2] = parseColorFunc(value);
      [r3, g2, b2] = transformMatrix(MATRIX_XYZ_TO_L_RGB, [x2, y2, z2], true);
    }
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value);
    [r3, g2, b2] = transformMatrix(MATRIX_XYZ_TO_L_RGB, [x2, y2, z2], true);
  }
  return [
    Math.min(Math.max(r3, 0), 1),
    Math.min(Math.max(g2, 0), 1),
    Math.min(Math.max(b2, 0), 1),
    alpha2
  ];
};
var convertColorToRgb = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let r3, g2, b2, alpha2;
  if (format === VAL_MIX) {
    let rgb2;
    if (value.startsWith(FN_COLOR)) {
      rgb2 = resolveColorFunc(value, opt);
    } else {
      rgb2 = resolveColorValue(value, opt);
    }
    if (rgb2 instanceof NullObject) {
      return rgb2;
    }
    [, r3, g2, b2, alpha2] = rgb2;
  } else if (value.startsWith(FN_COLOR)) {
    const [, val] = value.match(REG_FN_COLOR);
    const [cs] = val.replace("/", " ").split(/\s+/);
    if (cs === "srgb") {
      [, r3, g2, b2, alpha2] = resolveColorFunc(value, {
        format: VAL_COMP
      });
      r3 *= MAX_RGB;
      g2 *= MAX_RGB;
      b2 *= MAX_RGB;
    } else {
      [, r3, g2, b2, alpha2] = resolveColorFunc(value);
    }
  } else if (/^(?:ok)?l(?:ab|ch)/.test(value)) {
    [r3, g2, b2, alpha2] = convertColorToLinearRgb(value);
    [r3, g2, b2] = transformLinearRgbToRgb([r3, g2, b2]);
  } else {
    [, r3, g2, b2, alpha2] = resolveColorValue(value, {
      format: VAL_COMP
    });
  }
  return [r3, g2, b2, alpha2];
};
var convertColorToXyz = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { d50 = false, format = "" } = opt;
  let x2, y2, z2, alpha2;
  if (format === VAL_MIX) {
    let xyz;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    const [, val] = value.match(REG_FN_COLOR);
    const [cs] = val.replace("/", " ").split(/\s+/);
    if (d50) {
      if (cs === "xyz-d50") {
        [, x2, y2, z2, alpha2] = resolveColorFunc(value, {
          format: VAL_COMP
        });
      } else {
        [, x2, y2, z2, alpha2] = parseColorFunc(
          value,
          opt
        );
      }
    } else if (/^xyz(?:-d65)?$/.test(cs)) {
      [, x2, y2, z2, alpha2] = resolveColorFunc(value, {
        format: VAL_COMP
      });
    } else {
      [, x2, y2, z2, alpha2] = parseColorFunc(value);
    }
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value, opt);
  }
  return [x2, y2, z2, alpha2];
};
var convertColorToHsl = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let h2, s3, l2, alpha2;
  if (REG_HSL.test(value)) {
    [, h2, s3, l2, alpha2] = parseHsl(value, {
      format: "hsl"
    });
    if (format === "hsl") {
      return [Math.round(h2), Math.round(s3), Math.round(l2), alpha2];
    }
    return [h2, s3, l2, alpha2];
  }
  let x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    [, x2, y2, z2, alpha2] = parseColorFunc(value);
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value);
  }
  [h2, s3, l2] = transformXyzToHsl([x2, y2, z2], true);
  if (format === "hsl") {
    return [Math.round(h2), Math.round(s3), Math.round(l2), alpha2];
  }
  return [format === VAL_MIX && s3 === 0 ? NONE : h2, s3, l2, alpha2];
};
var convertColorToHwb = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let h2, w, b2, alpha2;
  if (REG_HWB.test(value)) {
    [, h2, w, b2, alpha2] = parseHwb(value, {
      format: "hwb"
    });
    if (format === "hwb") {
      return [Math.round(h2), Math.round(w), Math.round(b2), alpha2];
    }
    return [h2, w, b2, alpha2];
  }
  let x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    [, x2, y2, z2, alpha2] = parseColorFunc(value);
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value);
  }
  [h2, w, b2] = transformXyzToHwb([x2, y2, z2], true);
  if (format === "hwb") {
    return [Math.round(h2), Math.round(w), Math.round(b2), alpha2];
  }
  return [format === VAL_MIX && w + b2 >= 100 ? NONE : h2, w, b2, alpha2];
};
var convertColorToLab = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let l2, a3, b2, alpha2;
  if (REG_LAB.test(value)) {
    [, l2, a3, b2, alpha2] = parseLab(value, {
      format: VAL_COMP
    });
    return [l2, a3, b2, alpha2];
  }
  let x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    opt.d50 = true;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    [, x2, y2, z2, alpha2] = parseColorFunc(value, {
      d50: true
    });
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value, {
      d50: true
    });
  }
  [l2, a3, b2] = transformXyzD50ToLab([x2, y2, z2], true);
  return [l2, a3, b2, alpha2];
};
var convertColorToLch = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let l2, c3, h2, alpha2;
  if (REG_LCH.test(value)) {
    [, l2, c3, h2, alpha2] = parseLch(value, {
      format: VAL_COMP
    });
    return [l2, c3, h2, alpha2];
  }
  let x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    opt.d50 = true;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    [, x2, y2, z2, alpha2] = parseColorFunc(value, {
      d50: true
    });
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value, {
      d50: true
    });
  }
  [l2, c3, h2] = transformXyzD50ToLch([x2, y2, z2], true);
  return [l2, c3, format === VAL_MIX && c3 === 0 ? NONE : h2, alpha2];
};
var convertColorToOklab = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let l2, a3, b2, alpha2;
  if (REG_OKLAB.test(value)) {
    [, l2, a3, b2, alpha2] = parseOklab(value, {
      format: VAL_COMP
    });
    return [l2, a3, b2, alpha2];
  }
  let x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    [, x2, y2, z2, alpha2] = parseColorFunc(value);
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value);
  }
  [l2, a3, b2] = transformXyzToOklab([x2, y2, z2], true);
  return [l2, a3, b2, alpha2];
};
var convertColorToOklch = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "" } = opt;
  let l2, c3, h2, alpha2;
  if (REG_OKLCH.test(value)) {
    [, l2, c3, h2, alpha2] = parseOklch(value, {
      format: VAL_COMP
    });
    return [l2, c3, h2, alpha2];
  }
  let x2, y2, z2;
  if (format === VAL_MIX) {
    let xyz;
    if (value.startsWith(FN_COLOR)) {
      xyz = parseColorFunc(value, opt);
    } else {
      xyz = parseColorValue(value, opt);
    }
    if (xyz instanceof NullObject) {
      return xyz;
    }
    [, x2, y2, z2, alpha2] = xyz;
  } else if (value.startsWith(FN_COLOR)) {
    [, x2, y2, z2, alpha2] = parseColorFunc(value);
  } else {
    [, x2, y2, z2, alpha2] = parseColorValue(value);
  }
  [l2, c3, h2] = transformXyzToOklch([x2, y2, z2], true);
  return [l2, c3, format === VAL_MIX && c3 === 0 ? NONE : h2, alpha2];
};
var resolveColorMix = (value, opt = {}) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { format = "", nullable = false } = opt;
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE,
      name: "resolveColorMix",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    const cachedItem = cachedResult.item;
    if (isString(cachedItem)) {
      return cachedItem;
    }
    return cachedItem;
  }
  const nestedItems = [];
  let colorSpace = "";
  let hueArc = "";
  let colorA = "";
  let pctA = "";
  let colorB = "";
  let pctB = "";
  let parsed = false;
  if (!REG_MIX.test(value)) {
    if (value.startsWith(FN_MIX) && REG_MIX_NEST.test(value)) {
      const regColorSpace = new RegExp(`^(?:${CS_RGB}|${CS_XYZ})$`);
      const items = value.match(REG_MIX_NEST);
      for (const item of items) {
        if (item) {
          let val = resolveColorMix(item, {
            format: format === VAL_SPEC ? format : VAL_COMP
          });
          if (Array.isArray(val)) {
            const [cs, v1, v2, v3, v4] = val;
            if (v1 === 0 && v2 === 0 && v3 === 0 && v4 === 0) {
              value = "";
              break;
            }
            if (regColorSpace.test(cs)) {
              if (v4 === 1) {
                val = `color(${cs} ${v1} ${v2} ${v3})`;
              } else {
                val = `color(${cs} ${v1} ${v2} ${v3} / ${v4})`;
              }
            } else if (v4 === 1) {
              val = `${cs}(${v1} ${v2} ${v3})`;
            } else {
              val = `${cs}(${v1} ${v2} ${v3} / ${v4})`;
            }
          } else if (!REG_MIX.test(val)) {
            value = "";
            break;
          }
          nestedItems.push(val);
          value = value.replace(item, val);
        }
      }
      if (!value) {
        const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
        return res2;
      }
    } else if (value.startsWith(FN_MIX) && value.endsWith(")") && value.includes(FN_LIGHT_DARK)) {
      const regColorSpace = new RegExp(`in\\s+(${CS_MIX})`);
      const colorParts = value.replace(FN_MIX, "").replace(/\)$/, "");
      const [csPart = "", partA = "", partB = ""] = splitValue(colorParts, {
        delimiter: ","
      });
      const [colorPartA = "", pctPartA = ""] = splitValue(partA);
      const [colorPartB = "", pctPartB = ""] = splitValue(partB);
      const specifiedColorA = resolveColor(colorPartA, {
        format: VAL_SPEC
      });
      const specifiedColorB = resolveColor(colorPartB, {
        format: VAL_SPEC
      });
      if (regColorSpace.test(csPart) && specifiedColorA && specifiedColorB) {
        if (format === VAL_SPEC) {
          const [, cs] = csPart.match(regColorSpace);
          if (REG_CS_HUE.test(cs)) {
            [, colorSpace, hueArc] = cs.match(REG_CS_HUE);
          } else {
            colorSpace = cs;
          }
          colorA = specifiedColorA;
          if (pctPartA) {
            pctA = pctPartA;
          }
          colorB = specifiedColorB;
          if (pctPartB) {
            pctB = pctPartB;
          }
          value = value.replace(colorPartA, specifiedColorA).replace(colorPartB, specifiedColorB);
          parsed = true;
        } else {
          const resolvedColorA = resolveColor(colorPartA, opt);
          const resolvedColorB = resolveColor(colorPartB, opt);
          if (isString(resolvedColorA) && isString(resolvedColorB)) {
            value = value.replace(colorPartA, resolvedColorA).replace(colorPartB, resolvedColorB);
          }
        }
      } else {
        const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
        return res2;
      }
    } else {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
  }
  if (nestedItems.length && format === VAL_SPEC) {
    const regColorSpace = new RegExp(`^color-mix\\(\\s*in\\s+(${CS_MIX})\\s*,`);
    const [, cs] = value.match(regColorSpace);
    if (REG_CS_HUE.test(cs)) {
      [, colorSpace, hueArc] = cs.match(REG_CS_HUE);
    } else {
      colorSpace = cs;
    }
    if (nestedItems.length === 2) {
      let [itemA, itemB] = nestedItems;
      itemA = itemA.replace(/(?=[()])/g, "\\");
      itemB = itemB.replace(/(?=[()])/g, "\\");
      const regA = new RegExp(`(${itemA})(?:\\s+(${PCT}))?`);
      const regB = new RegExp(`(${itemB})(?:\\s+(${PCT}))?`);
      [, colorA, pctA] = value.match(regA);
      [, colorB, pctB] = value.match(regB);
    } else {
      let [item] = nestedItems;
      item = item.replace(/(?=[()])/g, "\\");
      const itemPart = `${item}(?:\\s+${PCT})?`;
      const itemPartCapt = `(${item})(?:\\s+(${PCT}))?`;
      const regItemPart = new RegExp(`^${itemPartCapt}$`);
      const regLastItem = new RegExp(`${itemPartCapt}\\s*\\)$`);
      const regColorPart = new RegExp(`^(${SYN_COLOR_TYPE})(?:\\s+(${PCT}))?$`);
      if (regLastItem.test(value)) {
        const reg = new RegExp(
          `(${SYN_MIX_PART})\\s*,\\s*(${itemPart})\\s*\\)$`
        );
        const [, colorPartA, colorPartB] = value.match(reg);
        [, colorA, pctA] = colorPartA.match(regColorPart);
        [, colorB, pctB] = colorPartB.match(regItemPart);
      } else {
        const reg = new RegExp(
          `(${itemPart})\\s*,\\s*(${SYN_MIX_PART})\\s*\\)$`
        );
        const [, colorPartA, colorPartB] = value.match(reg);
        [, colorA, pctA] = colorPartA.match(regItemPart);
        [, colorB, pctB] = colorPartB.match(regColorPart);
      }
    }
  } else if (!parsed) {
    const [, cs, colorPartA, colorPartB] = value.match(
      REG_MIX_CAPT
    );
    const reg = new RegExp(`^(${SYN_COLOR_TYPE})(?:\\s+(${PCT}))?$`);
    [, colorA, pctA] = colorPartA.match(reg);
    [, colorB, pctB] = colorPartB.match(reg);
    if (REG_CS_HUE.test(cs)) {
      [, colorSpace, hueArc] = cs.match(REG_CS_HUE);
    } else {
      colorSpace = cs;
    }
  }
  let pA, pB, m2;
  if (pctA && pctB) {
    const p1 = parseFloat(pctA) / MAX_PCT;
    const p2 = parseFloat(pctB) / MAX_PCT;
    if (p1 < 0 || p1 > 1 || p2 < 0 || p2 > 1 || p1 === 0 && p2 === 0) {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
    const factor = p1 + p2;
    pA = p1 / factor;
    pB = p2 / factor;
    m2 = factor < 1 ? factor : 1;
  } else {
    if (pctA) {
      pA = parseFloat(pctA) / MAX_PCT;
      if (pA < 0 || pA > 1) {
        const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
        return res2;
      }
      pB = 1 - pA;
    } else if (pctB) {
      pB = parseFloat(pctB) / MAX_PCT;
      if (pB < 0 || pB > 1) {
        const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
        return res2;
      }
      pA = 1 - pB;
    } else {
      pA = HALF;
      pB = HALF;
    }
    m2 = 1;
  }
  if (colorSpace === "xyz") {
    colorSpace = "xyz-d65";
  }
  if (format === VAL_SPEC) {
    let valueA = "";
    let valueB = "";
    if (colorA.startsWith(FN_MIX) || colorA.startsWith(FN_LIGHT_DARK)) {
      valueA = colorA;
    } else if (colorA.startsWith(FN_COLOR)) {
      const [cs, v1, v2, v3, v4] = parseColorFunc(
        colorA,
        opt
      );
      if (v4 === 1) {
        valueA = `color(${cs} ${v1} ${v2} ${v3})`;
      } else {
        valueA = `color(${cs} ${v1} ${v2} ${v3} / ${v4})`;
      }
    } else {
      const val = parseColorValue(colorA, opt);
      if (Array.isArray(val)) {
        const [cs, v1, v2, v3, v4] = val;
        if (v4 === 1) {
          if (cs === "rgb") {
            valueA = `${cs}(${v1}, ${v2}, ${v3})`;
          } else {
            valueA = `${cs}(${v1} ${v2} ${v3})`;
          }
        } else if (cs === "rgb") {
          valueA = `${cs}a(${v1}, ${v2}, ${v3}, ${v4})`;
        } else {
          valueA = `${cs}(${v1} ${v2} ${v3} / ${v4})`;
        }
      } else {
        if (!isString(val) || !val) {
          setCache(cacheKey, "");
          return "";
        }
        valueA = val;
      }
    }
    if (colorB.startsWith(FN_MIX) || colorB.startsWith(FN_LIGHT_DARK)) {
      valueB = colorB;
    } else if (colorB.startsWith(FN_COLOR)) {
      const [cs, v1, v2, v3, v4] = parseColorFunc(
        colorB,
        opt
      );
      if (v4 === 1) {
        valueB = `color(${cs} ${v1} ${v2} ${v3})`;
      } else {
        valueB = `color(${cs} ${v1} ${v2} ${v3} / ${v4})`;
      }
    } else {
      const val = parseColorValue(colorB, opt);
      if (Array.isArray(val)) {
        const [cs, v1, v2, v3, v4] = val;
        if (v4 === 1) {
          if (cs === "rgb") {
            valueB = `${cs}(${v1}, ${v2}, ${v3})`;
          } else {
            valueB = `${cs}(${v1} ${v2} ${v3})`;
          }
        } else if (cs === "rgb") {
          valueB = `${cs}a(${v1}, ${v2}, ${v3}, ${v4})`;
        } else {
          valueB = `${cs}(${v1} ${v2} ${v3} / ${v4})`;
        }
      } else {
        if (!isString(val) || !val) {
          setCache(cacheKey, "");
          return "";
        }
        valueB = val;
      }
    }
    if (pctA && pctB) {
      valueA += ` ${parseFloat(pctA)}%`;
      valueB += ` ${parseFloat(pctB)}%`;
    } else if (pctA) {
      const pA2 = parseFloat(pctA);
      if (pA2 !== MAX_PCT * HALF) {
        valueA += ` ${pA2}%`;
      }
    } else if (pctB) {
      const pA2 = MAX_PCT - parseFloat(pctB);
      if (pA2 !== MAX_PCT * HALF) {
        valueA += ` ${pA2}%`;
      }
    }
    if (hueArc) {
      const res2 = `color-mix(in ${colorSpace} ${hueArc} hue, ${valueA}, ${valueB})`;
      setCache(cacheKey, res2);
      return res2;
    } else {
      const res2 = `color-mix(in ${colorSpace}, ${valueA}, ${valueB})`;
      setCache(cacheKey, res2);
      return res2;
    }
  }
  let r3 = 0;
  let g2 = 0;
  let b2 = 0;
  let alpha2 = 0;
  if (/^srgb(?:-linear)?$/.test(colorSpace)) {
    let rgbA, rgbB;
    if (colorSpace === "srgb") {
      if (REG_CURRENT.test(colorA)) {
        rgbA = [NONE, NONE, NONE, NONE];
      } else {
        rgbA = convertColorToRgb(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        rgbB = [NONE, NONE, NONE, NONE];
      } else {
        rgbB = convertColorToRgb(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    } else {
      if (REG_CURRENT.test(colorA)) {
        rgbA = [NONE, NONE, NONE, NONE];
      } else {
        rgbA = convertColorToLinearRgb(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        rgbB = [NONE, NONE, NONE, NONE];
      } else {
        rgbB = convertColorToLinearRgb(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    }
    if (rgbA instanceof NullObject || rgbB instanceof NullObject) {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
    const [rrA, ggA, bbA, aaA] = rgbA;
    const [rrB, ggB, bbB, aaB] = rgbB;
    const rNone = rrA === NONE && rrB === NONE;
    const gNone = ggA === NONE && ggB === NONE;
    const bNone = bbA === NONE && bbB === NONE;
    const alphaNone = aaA === NONE && aaB === NONE;
    const [[rA, gA, bA, alphaA], [rB, gB, bB, alphaB]] = normalizeColorComponents(
      [rrA, ggA, bbA, aaA],
      [rrB, ggB, bbB, aaB],
      true
    );
    const factorA = alphaA * pA;
    const factorB = alphaB * pB;
    alpha2 = factorA + factorB;
    if (alpha2 === 0) {
      r3 = rA * pA + rB * pB;
      g2 = gA * pA + gB * pB;
      b2 = bA * pA + bB * pB;
    } else {
      r3 = (rA * factorA + rB * factorB) / alpha2;
      g2 = (gA * factorA + gB * factorB) / alpha2;
      b2 = (bA * factorA + bB * factorB) / alpha2;
      alpha2 = parseFloat(alpha2.toFixed(3));
    }
    if (format === VAL_COMP) {
      const res2 = [
        colorSpace,
        rNone ? NONE : roundToPrecision(r3, HEX),
        gNone ? NONE : roundToPrecision(g2, HEX),
        bNone ? NONE : roundToPrecision(b2, HEX),
        alphaNone ? NONE : alpha2 * m2
      ];
      setCache(cacheKey, res2);
      return res2;
    }
    r3 *= MAX_RGB;
    g2 *= MAX_RGB;
    b2 *= MAX_RGB;
  } else if (REG_CS_XYZ.test(colorSpace)) {
    let xyzA, xyzB;
    if (REG_CURRENT.test(colorA)) {
      xyzA = [NONE, NONE, NONE, NONE];
    } else {
      xyzA = convertColorToXyz(colorA, {
        colorSpace,
        d50: colorSpace === "xyz-d50",
        format: VAL_MIX
      });
    }
    if (REG_CURRENT.test(colorB)) {
      xyzB = [NONE, NONE, NONE, NONE];
    } else {
      xyzB = convertColorToXyz(colorB, {
        colorSpace,
        d50: colorSpace === "xyz-d50",
        format: VAL_MIX
      });
    }
    if (xyzA instanceof NullObject || xyzB instanceof NullObject) {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
    const [xxA, yyA, zzA, aaA] = xyzA;
    const [xxB, yyB, zzB, aaB] = xyzB;
    const xNone = xxA === NONE && xxB === NONE;
    const yNone = yyA === NONE && yyB === NONE;
    const zNone = zzA === NONE && zzB === NONE;
    const alphaNone = aaA === NONE && aaB === NONE;
    const [[xA, yA, zA, alphaA], [xB, yB, zB, alphaB]] = normalizeColorComponents(
      [xxA, yyA, zzA, aaA],
      [xxB, yyB, zzB, aaB],
      true
    );
    const factorA = alphaA * pA;
    const factorB = alphaB * pB;
    alpha2 = factorA + factorB;
    let x2, y2, z2;
    if (alpha2 === 0) {
      x2 = xA * pA + xB * pB;
      y2 = yA * pA + yB * pB;
      z2 = zA * pA + zB * pB;
    } else {
      x2 = (xA * factorA + xB * factorB) / alpha2;
      y2 = (yA * factorA + yB * factorB) / alpha2;
      z2 = (zA * factorA + zB * factorB) / alpha2;
      alpha2 = parseFloat(alpha2.toFixed(3));
    }
    if (format === VAL_COMP) {
      const res2 = [
        colorSpace,
        xNone ? NONE : roundToPrecision(x2, HEX),
        yNone ? NONE : roundToPrecision(y2, HEX),
        zNone ? NONE : roundToPrecision(z2, HEX),
        alphaNone ? NONE : alpha2 * m2
      ];
      setCache(cacheKey, res2);
      return res2;
    }
    if (colorSpace === "xyz-d50") {
      [r3, g2, b2] = transformXyzD50ToRgb([x2, y2, z2], true);
    } else {
      [r3, g2, b2] = transformXyzToRgb([x2, y2, z2], true);
    }
  } else if (/^h(?:sl|wb)$/.test(colorSpace)) {
    let hslA, hslB;
    if (colorSpace === "hsl") {
      if (REG_CURRENT.test(colorA)) {
        hslA = [NONE, NONE, NONE, NONE];
      } else {
        hslA = convertColorToHsl(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        hslB = [NONE, NONE, NONE, NONE];
      } else {
        hslB = convertColorToHsl(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    } else {
      if (REG_CURRENT.test(colorA)) {
        hslA = [NONE, NONE, NONE, NONE];
      } else {
        hslA = convertColorToHwb(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        hslB = [NONE, NONE, NONE, NONE];
      } else {
        hslB = convertColorToHwb(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    }
    if (hslA instanceof NullObject || hslB instanceof NullObject) {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
    const [hhA, ssA, llA, aaA] = hslA;
    const [hhB, ssB, llB, aaB] = hslB;
    const alphaNone = aaA === NONE && aaB === NONE;
    let [[hA, sA, lA, alphaA], [hB, sB, lB, alphaB]] = normalizeColorComponents(
      [hhA, ssA, llA, aaA],
      [hhB, ssB, llB, aaB],
      true
    );
    if (hueArc) {
      [hA, hB] = interpolateHue(hA, hB, hueArc);
    }
    const factorA = alphaA * pA;
    const factorB = alphaB * pB;
    alpha2 = factorA + factorB;
    const h2 = (hA * pA + hB * pB) % DEG;
    let s3, l2;
    if (alpha2 === 0) {
      s3 = sA * pA + sB * pB;
      l2 = lA * pA + lB * pB;
    } else {
      s3 = (sA * factorA + sB * factorB) / alpha2;
      l2 = (lA * factorA + lB * factorB) / alpha2;
      alpha2 = parseFloat(alpha2.toFixed(3));
    }
    [r3, g2, b2] = convertColorToRgb(
      `${colorSpace}(${h2} ${s3} ${l2})`
    );
    if (format === VAL_COMP) {
      const res2 = [
        "srgb",
        roundToPrecision(r3 / MAX_RGB, HEX),
        roundToPrecision(g2 / MAX_RGB, HEX),
        roundToPrecision(b2 / MAX_RGB, HEX),
        alphaNone ? NONE : alpha2 * m2
      ];
      setCache(cacheKey, res2);
      return res2;
    }
  } else if (/^(?:ok)?lch$/.test(colorSpace)) {
    let lchA, lchB;
    if (colorSpace === "lch") {
      if (REG_CURRENT.test(colorA)) {
        lchA = [NONE, NONE, NONE, NONE];
      } else {
        lchA = convertColorToLch(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        lchB = [NONE, NONE, NONE, NONE];
      } else {
        lchB = convertColorToLch(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    } else {
      if (REG_CURRENT.test(colorA)) {
        lchA = [NONE, NONE, NONE, NONE];
      } else {
        lchA = convertColorToOklch(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        lchB = [NONE, NONE, NONE, NONE];
      } else {
        lchB = convertColorToOklch(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    }
    if (lchA instanceof NullObject || lchB instanceof NullObject) {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
    const [llA, ccA, hhA, aaA] = lchA;
    const [llB, ccB, hhB, aaB] = lchB;
    const lNone = llA === NONE && llB === NONE;
    const cNone = ccA === NONE && ccB === NONE;
    const hNone = hhA === NONE && hhB === NONE;
    const alphaNone = aaA === NONE && aaB === NONE;
    let [[lA, cA, hA, alphaA], [lB, cB, hB, alphaB]] = normalizeColorComponents(
      [llA, ccA, hhA, aaA],
      [llB, ccB, hhB, aaB],
      true
    );
    if (hueArc) {
      [hA, hB] = interpolateHue(hA, hB, hueArc);
    }
    const factorA = alphaA * pA;
    const factorB = alphaB * pB;
    alpha2 = factorA + factorB;
    const h2 = (hA * pA + hB * pB) % DEG;
    let l2, c3;
    if (alpha2 === 0) {
      l2 = lA * pA + lB * pB;
      c3 = cA * pA + cB * pB;
    } else {
      l2 = (lA * factorA + lB * factorB) / alpha2;
      c3 = (cA * factorA + cB * factorB) / alpha2;
      alpha2 = parseFloat(alpha2.toFixed(3));
    }
    if (format === VAL_COMP) {
      const res2 = [
        colorSpace,
        lNone ? NONE : roundToPrecision(l2, HEX),
        cNone ? NONE : roundToPrecision(c3, HEX),
        hNone ? NONE : roundToPrecision(h2, HEX),
        alphaNone ? NONE : alpha2 * m2
      ];
      setCache(cacheKey, res2);
      return res2;
    }
    [, r3, g2, b2] = resolveColorValue(
      `${colorSpace}(${l2} ${c3} ${h2})`
    );
  } else {
    let labA, labB;
    if (colorSpace === "lab") {
      if (REG_CURRENT.test(colorA)) {
        labA = [NONE, NONE, NONE, NONE];
      } else {
        labA = convertColorToLab(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        labB = [NONE, NONE, NONE, NONE];
      } else {
        labB = convertColorToLab(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    } else {
      if (REG_CURRENT.test(colorA)) {
        labA = [NONE, NONE, NONE, NONE];
      } else {
        labA = convertColorToOklab(colorA, {
          colorSpace,
          format: VAL_MIX
        });
      }
      if (REG_CURRENT.test(colorB)) {
        labB = [NONE, NONE, NONE, NONE];
      } else {
        labB = convertColorToOklab(colorB, {
          colorSpace,
          format: VAL_MIX
        });
      }
    }
    if (labA instanceof NullObject || labB instanceof NullObject) {
      const res2 = cacheInvalidColorValue(cacheKey, format, nullable);
      return res2;
    }
    const [llA, aaA, bbA, alA] = labA;
    const [llB, aaB, bbB, alB] = labB;
    const lNone = llA === NONE && llB === NONE;
    const aNone = aaA === NONE && aaB === NONE;
    const bNone = bbA === NONE && bbB === NONE;
    const alphaNone = alA === NONE && alB === NONE;
    const [[lA, aA, bA, alphaA], [lB, aB, bB, alphaB]] = normalizeColorComponents(
      [llA, aaA, bbA, alA],
      [llB, aaB, bbB, alB],
      true
    );
    const factorA = alphaA * pA;
    const factorB = alphaB * pB;
    alpha2 = factorA + factorB;
    let l2, aO, bO;
    if (alpha2 === 0) {
      l2 = lA * pA + lB * pB;
      aO = aA * pA + aB * pB;
      bO = bA * pA + bB * pB;
    } else {
      l2 = (lA * factorA + lB * factorB) / alpha2;
      aO = (aA * factorA + aB * factorB) / alpha2;
      bO = (bA * factorA + bB * factorB) / alpha2;
      alpha2 = parseFloat(alpha2.toFixed(3));
    }
    if (format === VAL_COMP) {
      const res2 = [
        colorSpace,
        lNone ? NONE : roundToPrecision(l2, HEX),
        aNone ? NONE : roundToPrecision(aO, HEX),
        bNone ? NONE : roundToPrecision(bO, HEX),
        alphaNone ? NONE : alpha2 * m2
      ];
      setCache(cacheKey, res2);
      return res2;
    }
    [, r3, g2, b2] = resolveColorValue(
      `${colorSpace}(${l2} ${aO} ${bO})`
    );
  }
  const res = [
    "rgb",
    Math.round(r3),
    Math.round(g2),
    Math.round(b2),
    parseFloat((alpha2 * m2).toFixed(3))
  ];
  setCache(cacheKey, res);
  return res;
};
var import_css_tokenizer5 = (init_dist(), __toCommonJS(dist_exports));
var {
  CloseParen: PAREN_CLOSE,
  Comment: COMMENT,
  EOF,
  Ident: IDENT,
  Whitespace: W_SPACE
} = import_css_tokenizer5.TokenType;
var NAMESPACE2 = "css-var";
var REG_FN_CALC = new RegExp(SYN_FN_CALC);
var REG_FN_VAR = new RegExp(SYN_FN_VAR);
function resolveCustomProperty(tokens, opt = {}) {
  if (!Array.isArray(tokens)) {
    throw new TypeError(`${tokens} is not an array.`);
  }
  const { customProperty = {} } = opt;
  const items = [];
  while (tokens.length) {
    const token = tokens.shift();
    if (!Array.isArray(token)) {
      throw new TypeError(`${token} is not an array.`);
    }
    const [type, value] = token;
    if (type === PAREN_CLOSE) {
      break;
    }
    if (value === FN_VAR) {
      const [restTokens, item] = resolveCustomProperty(tokens, opt);
      tokens = restTokens;
      if (item) {
        items.push(item);
      }
    } else if (type === IDENT) {
      if (value.startsWith("--")) {
        let item;
        if (Object.hasOwn(customProperty, value)) {
          item = customProperty[value];
        } else if (typeof customProperty.callback === "function") {
          item = customProperty.callback(value);
        }
        if (item) {
          items.push(item);
        }
      } else if (value) {
        items.push(value);
      }
    }
  }
  let resolveAsColor = false;
  if (items.length > 1) {
    const lastValue = items[items.length - 1];
    resolveAsColor = isColor(lastValue);
  }
  let resolvedValue = "";
  for (let item of items) {
    item = item.trim();
    if (REG_FN_VAR.test(item)) {
      const resolvedItem = resolveVar(item, opt);
      if (isString(resolvedItem)) {
        if (resolveAsColor) {
          if (isColor(resolvedItem)) {
            resolvedValue = resolvedItem;
          }
        } else {
          resolvedValue = resolvedItem;
        }
      }
    } else if (REG_FN_CALC.test(item)) {
      item = cssCalc(item, opt);
      if (resolveAsColor) {
        if (isColor(item)) {
          resolvedValue = item;
        }
      } else {
        resolvedValue = item;
      }
    } else if (item && !/^(?:inherit|initial|revert(?:-layer)?|unset)$/.test(item)) {
      if (resolveAsColor) {
        if (isColor(item)) {
          resolvedValue = item;
        }
      } else {
        resolvedValue = item;
      }
    }
    if (resolvedValue) {
      break;
    }
  }
  return [tokens, resolvedValue];
}
function parseTokens(tokens, opt = {}) {
  const res = [];
  while (tokens.length) {
    const token = tokens.shift();
    const [type = "", value = ""] = token;
    if (value === FN_VAR) {
      const [restTokens, resolvedValue] = resolveCustomProperty(tokens, opt);
      if (!resolvedValue) {
        return new NullObject();
      }
      tokens = restTokens;
      res.push(resolvedValue);
    } else {
      switch (type) {
        case PAREN_CLOSE: {
          if (res.length) {
            const lastValue = res[res.length - 1];
            if (lastValue === " ") {
              res.splice(-1, 1, value);
            } else {
              res.push(value);
            }
          } else {
            res.push(value);
          }
          break;
        }
        case W_SPACE: {
          if (res.length) {
            const lastValue = res[res.length - 1];
            if (isString(lastValue) && !lastValue.endsWith("(") && lastValue !== " ") {
              res.push(value);
            }
          }
          break;
        }
        default: {
          if (type !== COMMENT && type !== EOF) {
            res.push(value);
          }
        }
      }
    }
  }
  return res;
}
function resolveVar(value, opt = {}) {
  const { format = "" } = opt;
  if (isString(value)) {
    if (!REG_FN_VAR.test(value) || format === VAL_SPEC) {
      return value;
    }
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE2,
      name: "resolveVar",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    return cachedResult.item;
  }
  const tokens = (0, import_css_tokenizer5.tokenize)({ css: value });
  const values = parseTokens(tokens, opt);
  if (Array.isArray(values)) {
    let color2 = values.join("");
    if (REG_FN_CALC.test(color2)) {
      color2 = cssCalc(color2, opt);
    }
    setCache(cacheKey, color2);
    return color2;
  } else {
    setCache(cacheKey, null);
    return new NullObject();
  }
}
var cssVar = (value, opt = {}) => {
  const resolvedValue = resolveVar(value, opt);
  if (isString(resolvedValue)) {
    return resolvedValue;
  }
  return "";
};
var import_css_color_parser = (init_dist5(), __toCommonJS(dist_exports4));
var import_css_parser_algorithms3 = (init_dist2(), __toCommonJS(dist_exports2));
var import_css_tokenizer22 = (init_dist(), __toCommonJS(dist_exports));
var {
  CloseParen: PAREN_CLOSE2,
  Comment: COMMENT2,
  Delim: DELIM,
  Dimension: DIM,
  EOF: EOF2,
  Function: FUNC,
  Ident: IDENT2,
  Number: NUM2,
  OpenParen: PAREN_OPEN,
  Percentage: PCT2,
  Whitespace: W_SPACE2
} = import_css_tokenizer22.TokenType;
var { HasNoneKeywords: KEY_NONE } = import_css_color_parser.SyntaxFlag;
var NAMESPACE3 = "relative-color";
var OCT2 = 8;
var DEC2 = 10;
var HEX2 = 16;
var MAX_PCT2 = 100;
var MAX_RGB2 = 255;
var REG_COLOR_CAPT = new RegExp(
  `^${FN_REL}(${SYN_COLOR_TYPE}|${SYN_MIX})\\s+`
);
var REG_CS_HSL = /(?:hsla?|hwb)$/;
var REG_CS_CIE = new RegExp(`^(?:${CS_LAB}|${CS_LCH})$`);
var REG_FN_CALC_SUM = /^(?:abs|sig?n|cos|tan)\(/;
var REG_FN_MATH_START = new RegExp(SYN_FN_MATH_START);
var REG_FN_REL = new RegExp(FN_REL);
var REG_FN_REL_CAPT = new RegExp(`^${FN_REL_CAPT}`);
var REG_FN_REL_START = new RegExp(`^${FN_REL}`);
var REG_FN_VAR2 = new RegExp(SYN_FN_VAR);
function resolveColorChannels(tokens, opt = {}) {
  if (!Array.isArray(tokens)) {
    throw new TypeError(`${tokens} is not an array.`);
  }
  const { colorSpace = "", format = "" } = opt;
  const colorChannels = /* @__PURE__ */ new Map([
    ["color", ["r", "g", "b", "alpha"]],
    ["hsl", ["h", "s", "l", "alpha"]],
    ["hsla", ["h", "s", "l", "alpha"]],
    ["hwb", ["h", "w", "b", "alpha"]],
    ["lab", ["l", "a", "b", "alpha"]],
    ["lch", ["l", "c", "h", "alpha"]],
    ["oklab", ["l", "a", "b", "alpha"]],
    ["oklch", ["l", "c", "h", "alpha"]],
    ["rgb", ["r", "g", "b", "alpha"]],
    ["rgba", ["r", "g", "b", "alpha"]]
  ]);
  const colorChannel = colorChannels.get(colorSpace);
  if (!colorChannel) {
    return new NullObject();
  }
  const mathFunc = /* @__PURE__ */ new Set();
  const channels = [[], [], [], []];
  let i3 = 0;
  let nest = 0;
  let func = "";
  let precededPct = false;
  while (tokens.length) {
    const token = tokens.shift();
    if (!Array.isArray(token)) {
      throw new TypeError(`${token} is not an array.`);
    }
    const [type, value, , , detail] = token;
    const channel = channels[i3];
    if (Array.isArray(channel)) {
      switch (type) {
        case DELIM: {
          if (func) {
            if ((value === "+" || value === "-") && precededPct && !REG_FN_CALC_SUM.test(func)) {
              return new NullObject();
            }
            precededPct = false;
            channel.push(value);
          }
          break;
        }
        case DIM: {
          if (!func || !REG_FN_CALC_SUM.test(func)) {
            return new NullObject();
          }
          const resolvedValue = resolveDimension(token, opt);
          if (isString(resolvedValue)) {
            channel.push(resolvedValue);
          } else {
            channel.push(value);
          }
          break;
        }
        case FUNC: {
          channel.push(value);
          func = value;
          nest++;
          if (REG_FN_MATH_START.test(value)) {
            mathFunc.add(nest);
          }
          break;
        }
        case IDENT2: {
          if (!colorChannel.includes(value)) {
            return new NullObject();
          }
          channel.push(value);
          if (!func) {
            i3++;
          }
          break;
        }
        case NUM2: {
          channel.push(Number(detail?.value));
          if (!func) {
            i3++;
          }
          break;
        }
        case PAREN_OPEN: {
          channel.push(value);
          nest++;
          break;
        }
        case PAREN_CLOSE2: {
          if (func) {
            const lastValue = channel[channel.length - 1];
            if (lastValue === " ") {
              channel.splice(-1, 1, value);
            } else {
              channel.push(value);
            }
            if (mathFunc.has(nest)) {
              mathFunc.delete(nest);
            }
            nest--;
            if (nest === 0) {
              func = "";
              i3++;
            }
          }
          break;
        }
        case PCT2: {
          if (!func) {
            return new NullObject();
          } else if (!REG_FN_CALC_SUM.test(func)) {
            const lastValue = channel.toReversed().find((v) => v !== " ");
            if (lastValue === "+" || lastValue === "-") {
              return new NullObject();
            } else if (lastValue === "*" || lastValue === "/") {
              precededPct = false;
            } else {
              precededPct = true;
            }
          }
          channel.push(Number(detail?.value) / MAX_PCT2);
          if (!func) {
            i3++;
          }
          break;
        }
        case W_SPACE2: {
          if (channel.length && func) {
            const lastValue = channel[channel.length - 1];
            if (typeof lastValue === "number") {
              channel.push(value);
            } else if (isString(lastValue) && !lastValue.endsWith("(") && lastValue !== " ") {
              channel.push(value);
            }
          }
          break;
        }
        default: {
          if (type !== COMMENT2 && type !== EOF2 && func) {
            channel.push(value);
          }
        }
      }
    }
  }
  const channelValues = [];
  for (const channel of channels) {
    if (channel.length === 1) {
      const [resolvedValue] = channel;
      if (isStringOrNumber(resolvedValue)) {
        channelValues.push(resolvedValue);
      }
    } else if (channel.length) {
      const resolvedValue = serializeCalc(channel.join(""), {
        format
      });
      channelValues.push(resolvedValue);
    }
  }
  return channelValues;
}
function extractOriginColor(value, opt = {}) {
  const { colorScheme = "normal", currentColor = "", format = "" } = opt;
  if (isString(value)) {
    value = value.toLowerCase().trim();
    if (!value) {
      return new NullObject();
    }
    if (!REG_FN_REL_START.test(value)) {
      return value;
    }
  } else {
    return new NullObject();
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE3,
      name: "extractOriginColor",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    return cachedResult.item;
  }
  if (/currentcolor/.test(value)) {
    if (currentColor) {
      value = value.replace(/currentcolor/g, currentColor);
    } else {
      setCache(cacheKey, null);
      return new NullObject();
    }
  }
  let colorSpace = "";
  if (REG_FN_REL_CAPT.test(value)) {
    [, colorSpace] = value.match(REG_FN_REL_CAPT);
  }
  opt.colorSpace = colorSpace;
  if (value.includes(FN_LIGHT_DARK)) {
    const colorParts = value.replace(new RegExp(`^${colorSpace}\\(`), "").replace(/\)$/, "");
    const [, originColor = ""] = splitValue(colorParts);
    const specifiedOriginColor = resolveColor(originColor, {
      colorScheme,
      format: VAL_SPEC
    });
    if (specifiedOriginColor === "") {
      setCache(cacheKey, null);
      return new NullObject();
    }
    if (format === VAL_SPEC) {
      value = value.replace(originColor, specifiedOriginColor);
    } else {
      const resolvedOriginColor = resolveColor(specifiedOriginColor, opt);
      if (isString(resolvedOriginColor)) {
        value = value.replace(originColor, resolvedOriginColor);
      }
    }
  }
  if (REG_COLOR_CAPT.test(value)) {
    const [, originColor] = value.match(REG_COLOR_CAPT);
    const [, restValue] = value.split(originColor);
    if (/^[a-z]+$/.test(originColor)) {
      if (!/^transparent$/.test(originColor) && !Object.hasOwn(NAMED_COLORS, originColor)) {
        setCache(cacheKey, null);
        return new NullObject();
      }
    } else if (format === VAL_SPEC) {
      const resolvedOriginColor = resolveColor(originColor, opt);
      if (isString(resolvedOriginColor)) {
        value = value.replace(originColor, resolvedOriginColor);
      }
    }
    if (format === VAL_SPEC) {
      const tokens = (0, import_css_tokenizer22.tokenize)({ css: restValue });
      const channelValues = resolveColorChannels(tokens, opt);
      if (channelValues instanceof NullObject) {
        setCache(cacheKey, null);
        return channelValues;
      }
      const [v1, v2, v3, v4] = channelValues;
      let channelValue = "";
      if (isStringOrNumber(v4)) {
        channelValue = ` ${v1} ${v2} ${v3} / ${v4})`;
      } else {
        channelValue = ` ${channelValues.join(" ")})`;
      }
      if (restValue !== channelValue) {
        value = value.replace(restValue, channelValue);
      }
    }
  } else {
    const [, restValue] = value.split(REG_FN_REL_START);
    const tokens = (0, import_css_tokenizer22.tokenize)({ css: restValue });
    const originColor = [];
    let nest = 0;
    while (tokens.length) {
      const [type, tokenValue] = tokens.shift();
      switch (type) {
        case FUNC:
        case PAREN_OPEN: {
          originColor.push(tokenValue);
          nest++;
          break;
        }
        case PAREN_CLOSE2: {
          const lastValue = originColor[originColor.length - 1];
          if (lastValue === " ") {
            originColor.splice(-1, 1, tokenValue);
          } else if (isString(lastValue)) {
            originColor.push(tokenValue);
          }
          nest--;
          break;
        }
        case W_SPACE2: {
          const lastValue = originColor[originColor.length - 1];
          if (isString(lastValue) && !lastValue.endsWith("(") && lastValue !== " ") {
            originColor.push(tokenValue);
          }
          break;
        }
        default: {
          if (type !== COMMENT2 && type !== EOF2) {
            originColor.push(tokenValue);
          }
        }
      }
      if (nest === 0) {
        break;
      }
    }
    const resolvedOriginColor = resolveRelativeColor(
      originColor.join("").trim(),
      opt
    );
    if (resolvedOriginColor instanceof NullObject) {
      setCache(cacheKey, null);
      return resolvedOriginColor;
    }
    const channelValues = resolveColorChannels(tokens, opt);
    if (channelValues instanceof NullObject) {
      setCache(cacheKey, null);
      return channelValues;
    }
    const [v1, v2, v3, v4] = channelValues;
    let channelValue = "";
    if (isStringOrNumber(v4)) {
      channelValue = ` ${v1} ${v2} ${v3} / ${v4})`;
    } else {
      channelValue = ` ${channelValues.join(" ")})`;
    }
    value = value.replace(restValue, `${resolvedOriginColor}${channelValue}`);
  }
  setCache(cacheKey, value);
  return value;
}
function resolveRelativeColor(value, opt = {}) {
  const { format = "" } = opt;
  if (isString(value)) {
    if (REG_FN_VAR2.test(value)) {
      if (format === VAL_SPEC) {
        return value;
      } else {
        throw new SyntaxError(`Unexpected token ${FN_VAR} found.`);
      }
    } else if (!REG_FN_REL.test(value)) {
      return value;
    }
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE3,
      name: "resolveRelativeColor",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    return cachedResult.item;
  }
  const originColor = extractOriginColor(value, opt);
  if (originColor instanceof NullObject) {
    setCache(cacheKey, null);
    return originColor;
  }
  value = originColor;
  if (format === VAL_SPEC) {
    if (value.startsWith("rgba(")) {
      value = value.replace(/^rgba\(/, "rgb(");
    } else if (value.startsWith("hsla(")) {
      value = value.replace(/^hsla\(/, "hsl(");
    }
    return value;
  }
  const tokens = (0, import_css_tokenizer22.tokenize)({ css: value });
  const components = (0, import_css_parser_algorithms3.parseComponentValue)(tokens);
  const parsedComponents = (0, import_css_color_parser.color)(components);
  if (!parsedComponents) {
    setCache(cacheKey, null);
    return new NullObject();
  }
  const {
    alpha: alphaComponent,
    channels: channelsComponent,
    colorNotation,
    syntaxFlags
  } = parsedComponents;
  let alpha2;
  if (Number.isNaN(Number(alphaComponent))) {
    if (syntaxFlags instanceof Set && syntaxFlags.has(KEY_NONE)) {
      alpha2 = NONE;
    } else {
      alpha2 = 0;
    }
  } else {
    alpha2 = roundToPrecision(Number(alphaComponent), OCT2);
  }
  let v1;
  let v2;
  let v3;
  [v1, v2, v3] = channelsComponent;
  let resolvedValue;
  if (REG_CS_CIE.test(colorNotation)) {
    const hasNone = syntaxFlags instanceof Set && syntaxFlags.has(KEY_NONE);
    if (Number.isNaN(v1)) {
      if (hasNone) {
        v1 = NONE;
      } else {
        v1 = 0;
      }
    } else {
      v1 = roundToPrecision(v1, HEX2);
    }
    if (Number.isNaN(v2)) {
      if (hasNone) {
        v2 = NONE;
      } else {
        v2 = 0;
      }
    } else {
      v2 = roundToPrecision(v2, HEX2);
    }
    if (Number.isNaN(v3)) {
      if (hasNone) {
        v3 = NONE;
      } else {
        v3 = 0;
      }
    } else {
      v3 = roundToPrecision(v3, HEX2);
    }
    if (alpha2 === 1) {
      resolvedValue = `${colorNotation}(${v1} ${v2} ${v3})`;
    } else {
      resolvedValue = `${colorNotation}(${v1} ${v2} ${v3} / ${alpha2})`;
    }
  } else if (REG_CS_HSL.test(colorNotation)) {
    if (Number.isNaN(v1)) {
      v1 = 0;
    }
    if (Number.isNaN(v2)) {
      v2 = 0;
    }
    if (Number.isNaN(v3)) {
      v3 = 0;
    }
    let [r3, g2, b2] = convertColorToRgb(
      `${colorNotation}(${v1} ${v2} ${v3} / ${alpha2})`
    );
    r3 = roundToPrecision(r3 / MAX_RGB2, DEC2);
    g2 = roundToPrecision(g2 / MAX_RGB2, DEC2);
    b2 = roundToPrecision(b2 / MAX_RGB2, DEC2);
    if (alpha2 === 1) {
      resolvedValue = `color(srgb ${r3} ${g2} ${b2})`;
    } else {
      resolvedValue = `color(srgb ${r3} ${g2} ${b2} / ${alpha2})`;
    }
  } else {
    const cs = colorNotation === "rgb" ? "srgb" : colorNotation;
    const hasNone = syntaxFlags instanceof Set && syntaxFlags.has(KEY_NONE);
    if (Number.isNaN(v1)) {
      if (hasNone) {
        v1 = NONE;
      } else {
        v1 = 0;
      }
    } else {
      v1 = roundToPrecision(v1, DEC2);
    }
    if (Number.isNaN(v2)) {
      if (hasNone) {
        v2 = NONE;
      } else {
        v2 = 0;
      }
    } else {
      v2 = roundToPrecision(v2, DEC2);
    }
    if (Number.isNaN(v3)) {
      if (hasNone) {
        v3 = NONE;
      } else {
        v3 = 0;
      }
    } else {
      v3 = roundToPrecision(v3, DEC2);
    }
    if (alpha2 === 1) {
      resolvedValue = `color(${cs} ${v1} ${v2} ${v3})`;
    } else {
      resolvedValue = `color(${cs} ${v1} ${v2} ${v3} / ${alpha2})`;
    }
  }
  setCache(cacheKey, resolvedValue);
  return resolvedValue;
}
var NAMESPACE4 = "resolve";
var RGB_TRANSPARENT = "rgba(0, 0, 0, 0)";
var REG_FN_CALC2 = new RegExp(SYN_FN_CALC);
var REG_FN_LIGHT_DARK = new RegExp(SYN_FN_LIGHT_DARK);
var REG_FN_REL2 = new RegExp(SYN_FN_REL);
var REG_FN_VAR3 = new RegExp(SYN_FN_VAR);
var resolveColor = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const {
    colorScheme = "normal",
    currentColor = "",
    format = VAL_COMP,
    nullable = false
  } = opt;
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE4,
      name: "resolve",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    return cachedResult.item;
  }
  if (REG_FN_VAR3.test(value)) {
    if (format === VAL_SPEC) {
      setCache(cacheKey, value);
      return value;
    }
    const resolvedValue = resolveVar(value, opt);
    if (resolvedValue instanceof NullObject) {
      switch (format) {
        case "hex":
        case "hexAlpha": {
          setCache(cacheKey, resolvedValue);
          return resolvedValue;
        }
        default: {
          if (nullable) {
            setCache(cacheKey, resolvedValue);
            return resolvedValue;
          }
          const res2 = RGB_TRANSPARENT;
          setCache(cacheKey, res2);
          return res2;
        }
      }
    } else {
      value = resolvedValue;
    }
  }
  if (opt.format !== format) {
    opt.format = format;
  }
  value = value.toLowerCase();
  if (REG_FN_LIGHT_DARK.test(value) && value.endsWith(")")) {
    const colorParts = value.replace(REG_FN_LIGHT_DARK, "").replace(/\)$/, "");
    const [light = "", dark = ""] = splitValue(colorParts, {
      delimiter: ","
    });
    if (light && dark) {
      if (format === VAL_SPEC) {
        const lightColor = resolveColor(light, opt);
        const darkColor = resolveColor(dark, opt);
        let res3;
        if (lightColor && darkColor) {
          res3 = `light-dark(${lightColor}, ${darkColor})`;
        } else {
          res3 = "";
        }
        setCache(cacheKey, res3);
        return res3;
      }
      let resolvedValue;
      if (colorScheme === "dark") {
        resolvedValue = resolveColor(dark, opt);
      } else {
        resolvedValue = resolveColor(light, opt);
      }
      let res2;
      if (resolvedValue instanceof NullObject) {
        if (nullable) {
          res2 = resolvedValue;
        } else {
          res2 = RGB_TRANSPARENT;
        }
      } else {
        res2 = resolvedValue;
      }
      setCache(cacheKey, res2);
      return res2;
    }
    switch (format) {
      case VAL_SPEC: {
        setCache(cacheKey, "");
        return "";
      }
      case "hex":
      case "hexAlpha": {
        setCache(cacheKey, null);
        return new NullObject();
      }
      case VAL_COMP:
      default: {
        const res2 = RGB_TRANSPARENT;
        setCache(cacheKey, res2);
        return res2;
      }
    }
  }
  if (REG_FN_REL2.test(value)) {
    const resolvedValue = resolveRelativeColor(value, opt);
    if (format === VAL_COMP) {
      let res2;
      if (resolvedValue instanceof NullObject) {
        if (nullable) {
          res2 = resolvedValue;
        } else {
          res2 = RGB_TRANSPARENT;
        }
      } else {
        res2 = resolvedValue;
      }
      setCache(cacheKey, res2);
      return res2;
    }
    if (format === VAL_SPEC) {
      let res2 = "";
      if (resolvedValue instanceof NullObject) {
        res2 = "";
      } else {
        res2 = resolvedValue;
      }
      setCache(cacheKey, res2);
      return res2;
    }
    if (resolvedValue instanceof NullObject) {
      value = "";
    } else {
      value = resolvedValue;
    }
  }
  if (REG_FN_CALC2.test(value)) {
    value = cssCalc(value, opt);
  }
  let cs = "";
  let r3 = NaN;
  let g2 = NaN;
  let b2 = NaN;
  let alpha2 = NaN;
  if (value === "transparent") {
    switch (format) {
      case VAL_SPEC: {
        setCache(cacheKey, value);
        return value;
      }
      case "hex": {
        setCache(cacheKey, null);
        return new NullObject();
      }
      case "hexAlpha": {
        const res2 = "#00000000";
        setCache(cacheKey, res2);
        return res2;
      }
      case VAL_COMP:
      default: {
        const res2 = RGB_TRANSPARENT;
        setCache(cacheKey, res2);
        return res2;
      }
    }
  } else if (value === "currentcolor") {
    if (format === VAL_SPEC) {
      setCache(cacheKey, value);
      return value;
    }
    if (currentColor) {
      let resolvedValue;
      if (currentColor.startsWith(FN_MIX)) {
        resolvedValue = resolveColorMix(currentColor, opt);
      } else if (currentColor.startsWith(FN_COLOR)) {
        resolvedValue = resolveColorFunc(currentColor, opt);
      } else {
        resolvedValue = resolveColorValue(currentColor, opt);
      }
      if (resolvedValue instanceof NullObject) {
        setCache(cacheKey, resolvedValue);
        return resolvedValue;
      }
      [cs, r3, g2, b2, alpha2] = resolvedValue;
    } else if (format === VAL_COMP) {
      const res2 = RGB_TRANSPARENT;
      setCache(cacheKey, res2);
      return res2;
    }
  } else if (format === VAL_SPEC) {
    if (value.startsWith(FN_MIX)) {
      const res2 = resolveColorMix(value, opt);
      setCache(cacheKey, res2);
      return res2;
    } else if (value.startsWith(FN_COLOR)) {
      const [scs, rr, gg, bb, aa] = resolveColorFunc(
        value,
        opt
      );
      let res2 = "";
      if (aa === 1) {
        res2 = `color(${scs} ${rr} ${gg} ${bb})`;
      } else {
        res2 = `color(${scs} ${rr} ${gg} ${bb} / ${aa})`;
      }
      setCache(cacheKey, res2);
      return res2;
    } else {
      const rgb2 = resolveColorValue(value, opt);
      if (isString(rgb2)) {
        setCache(cacheKey, rgb2);
        return rgb2;
      }
      const [scs, rr, gg, bb, aa] = rgb2;
      let res2 = "";
      if (scs === "rgb") {
        if (aa === 1) {
          res2 = `${scs}(${rr}, ${gg}, ${bb})`;
        } else {
          res2 = `${scs}a(${rr}, ${gg}, ${bb}, ${aa})`;
        }
      } else if (aa === 1) {
        res2 = `${scs}(${rr} ${gg} ${bb})`;
      } else {
        res2 = `${scs}(${rr} ${gg} ${bb} / ${aa})`;
      }
      setCache(cacheKey, res2);
      return res2;
    }
  } else if (value.startsWith(FN_MIX)) {
    if (/currentcolor/.test(value)) {
      if (currentColor) {
        value = value.replace(/currentcolor/g, currentColor);
      }
    }
    if (/transparent/.test(value)) {
      value = value.replace(/transparent/g, RGB_TRANSPARENT);
    }
    const resolvedValue = resolveColorMix(value, opt);
    if (resolvedValue instanceof NullObject) {
      setCache(cacheKey, resolvedValue);
      return resolvedValue;
    }
    [cs, r3, g2, b2, alpha2] = resolvedValue;
  } else if (value.startsWith(FN_COLOR)) {
    const resolvedValue = resolveColorFunc(value, opt);
    if (resolvedValue instanceof NullObject) {
      setCache(cacheKey, resolvedValue);
      return resolvedValue;
    }
    [cs, r3, g2, b2, alpha2] = resolvedValue;
  } else if (value) {
    const resolvedValue = resolveColorValue(value, opt);
    if (resolvedValue instanceof NullObject) {
      setCache(cacheKey, resolvedValue);
      return resolvedValue;
    }
    [cs, r3, g2, b2, alpha2] = resolvedValue;
  }
  let res = "";
  switch (format) {
    case "hex": {
      if (Number.isNaN(r3) || Number.isNaN(g2) || Number.isNaN(b2) || Number.isNaN(alpha2) || alpha2 === 0) {
        setCache(cacheKey, null);
        return new NullObject();
      }
      res = convertRgbToHex([r3, g2, b2, 1]);
      break;
    }
    case "hexAlpha": {
      if (Number.isNaN(r3) || Number.isNaN(g2) || Number.isNaN(b2) || Number.isNaN(alpha2)) {
        setCache(cacheKey, null);
        return new NullObject();
      }
      res = convertRgbToHex([r3, g2, b2, alpha2]);
      break;
    }
    case VAL_COMP:
    default: {
      switch (cs) {
        case "rgb": {
          if (alpha2 === 1) {
            res = `${cs}(${r3}, ${g2}, ${b2})`;
          } else {
            res = `${cs}a(${r3}, ${g2}, ${b2}, ${alpha2})`;
          }
          break;
        }
        case "lab":
        case "lch":
        case "oklab":
        case "oklch": {
          if (alpha2 === 1) {
            res = `${cs}(${r3} ${g2} ${b2})`;
          } else {
            res = `${cs}(${r3} ${g2} ${b2} / ${alpha2})`;
          }
          break;
        }
        default: {
          if (alpha2 === 1) {
            res = `color(${cs} ${r3} ${g2} ${b2})`;
          } else {
            res = `color(${cs} ${r3} ${g2} ${b2} / ${alpha2})`;
          }
        }
      }
    }
  }
  setCache(cacheKey, res);
  return res;
};
var resolve = (value, opt = {}) => {
  opt.nullable = false;
  const resolvedValue = resolveColor(value, opt);
  if (resolvedValue instanceof NullObject) {
    return null;
  }
  return resolvedValue;
};
var {
  CloseParen: PAREN_CLOSE3,
  Comma: COMMA,
  Comment: COMMENT3,
  Delim: DELIM2,
  EOF: EOF3,
  Function: FUNC2,
  Ident: IDENT3,
  OpenParen: PAREN_OPEN2,
  Whitespace: W_SPACE3
} = import_css_tokenizer32.TokenType;
var NAMESPACE5 = "util";
var DEC3 = 10;
var HEX3 = 16;
var DEG2 = 360;
var DEG_HALF2 = 180;
var REG_COLOR2 = new RegExp(`^(?:${SYN_COLOR_TYPE})$`);
var REG_FN_COLOR2 = /^(?:(?:ok)?l(?:ab|ch)|color(?:-mix)?|hsla?|hwb|rgba?|var)\(/;
var REG_MIX2 = new RegExp(SYN_MIX);
var splitValue = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { delimiter = " ", preserveComment = false } = opt;
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE5,
      name: "splitValue",
      value
    },
    {
      delimiter,
      preserveComment
    }
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  let regDelimiter;
  if (delimiter === ",") {
    regDelimiter = /^,$/;
  } else if (delimiter === "/") {
    regDelimiter = /^\/$/;
  } else {
    regDelimiter = /^\s+$/;
  }
  const tokens = (0, import_css_tokenizer32.tokenize)({ css: value });
  let nest = 0;
  let str = "";
  const res = [];
  while (tokens.length) {
    const [type, value2] = tokens.shift();
    switch (type) {
      case COMMA: {
        if (regDelimiter.test(value2)) {
          if (nest === 0) {
            res.push(str.trim());
            str = "";
          } else {
            str += value2;
          }
        } else {
          str += value2;
        }
        break;
      }
      case DELIM2: {
        if (regDelimiter.test(value2)) {
          if (nest === 0) {
            res.push(str.trim());
            str = "";
          } else {
            str += value2;
          }
        } else {
          str += value2;
        }
        break;
      }
      case COMMENT3: {
        if (preserveComment && (delimiter === "," || delimiter === "/")) {
          str += value2;
        }
        break;
      }
      case FUNC2:
      case PAREN_OPEN2: {
        str += value2;
        nest++;
        break;
      }
      case PAREN_CLOSE3: {
        str += value2;
        nest--;
        break;
      }
      case W_SPACE3: {
        if (regDelimiter.test(value2)) {
          if (nest === 0) {
            if (str) {
              res.push(str.trim());
              str = "";
            }
          } else {
            str += " ";
          }
        } else if (!str.endsWith(" ")) {
          str += " ";
        }
        break;
      }
      default: {
        if (type === EOF3) {
          res.push(str.trim());
          str = "";
        } else {
          str += value2;
        }
      }
    }
  }
  setCache(cacheKey, res);
  return res;
};
var extractDashedIdent = (value) => {
  if (isString(value)) {
    value = value.trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey({
    namespace: NAMESPACE5,
    name: "extractDashedIdent",
    value
  });
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const tokens = (0, import_css_tokenizer32.tokenize)({ css: value });
  const items = /* @__PURE__ */ new Set();
  while (tokens.length) {
    const [type, value2] = tokens.shift();
    if (type === IDENT3 && value2.startsWith("--")) {
      items.add(value2);
    }
  }
  const res = [...items];
  setCache(cacheKey, res);
  return res;
};
var isColor = (value, opt = {}) => {
  if (isString(value)) {
    value = value.toLowerCase().trim();
    if (value && isString(value)) {
      if (/^[a-z]+$/.test(value)) {
        if (/^(?:currentcolor|transparent)$/.test(value) || Object.hasOwn(NAMED_COLORS, value)) {
          return true;
        }
      } else if (REG_COLOR2.test(value) || REG_MIX2.test(value)) {
        return true;
      } else if (REG_FN_COLOR2.test(value)) {
        opt.nullable = true;
        if (!opt.format) {
          opt.format = VAL_SPEC;
        }
        const resolvedValue = resolveColor(value, opt);
        if (resolvedValue) {
          return true;
        }
      }
    }
  }
  return false;
};
var valueToJsonString = (value, func = false) => {
  if (typeof value === "undefined") {
    return "";
  }
  const res = JSON.stringify(value, (_key, val) => {
    let replacedValue;
    if (typeof val === "undefined") {
      replacedValue = null;
    } else if (typeof val === "function") {
      if (func) {
        replacedValue = val.toString().replace(/\s/g, "").substring(0, HEX3);
      } else {
        replacedValue = val.name;
      }
    } else if (val instanceof Map || val instanceof Set) {
      replacedValue = [...val];
    } else if (typeof val === "bigint") {
      replacedValue = val.toString();
    } else {
      replacedValue = val;
    }
    return replacedValue;
  });
  return res;
};
var roundToPrecision = (value, bit = 0) => {
  if (!Number.isFinite(value)) {
    throw new TypeError(`${value} is not a finite number.`);
  }
  if (!Number.isFinite(bit)) {
    throw new TypeError(`${bit} is not a finite number.`);
  } else if (bit < 0 || bit > HEX3) {
    throw new RangeError(`${bit} is not between 0 and ${HEX3}.`);
  }
  if (bit === 0) {
    return Math.round(value);
  }
  let val;
  if (bit === HEX3) {
    val = value.toPrecision(6);
  } else if (bit < DEC3) {
    val = value.toPrecision(4);
  } else {
    val = value.toPrecision(5);
  }
  return parseFloat(val);
};
var interpolateHue = (hueA, hueB, arc = "shorter") => {
  if (!Number.isFinite(hueA)) {
    throw new TypeError(`${hueA} is not a finite number.`);
  }
  if (!Number.isFinite(hueB)) {
    throw new TypeError(`${hueB} is not a finite number.`);
  }
  switch (arc) {
    case "decreasing": {
      if (hueB > hueA) {
        hueA += DEG2;
      }
      break;
    }
    case "increasing": {
      if (hueB < hueA) {
        hueB += DEG2;
      }
      break;
    }
    case "longer": {
      if (hueB > hueA && hueB < hueA + DEG_HALF2) {
        hueA += DEG2;
      } else if (hueB > hueA + DEG_HALF2 * -1 && hueB <= hueA) {
        hueB += DEG2;
      }
      break;
    }
    case "shorter":
    default: {
      if (hueB > hueA + DEG_HALF2) {
        hueA += DEG2;
      } else if (hueB < hueA + DEG_HALF2 * -1) {
        hueB += DEG2;
      }
    }
  }
  return [hueA, hueB];
};
var absoluteFontSize = /* @__PURE__ */ new Map([
  ["xx-small", 3 / 5],
  ["x-small", 3 / 4],
  ["small", 8 / 9],
  ["medium", 1],
  ["large", 6 / 5],
  ["x-large", 3 / 2],
  ["xx-large", 2],
  ["xxx-large", 3]
]);
var relativeFontSize = /* @__PURE__ */ new Map([
  ["smaller", 1 / 1.2],
  ["larger", 1.2]
]);
var absoluteLength = /* @__PURE__ */ new Map([
  ["cm", 96 / 2.54],
  ["mm", 96 / 2.54 / 10],
  ["q", 96 / 2.54 / 40],
  ["in", 96],
  ["pc", 96 / 6],
  ["pt", 96 / 72],
  ["px", 1]
]);
var relativeLength = /* @__PURE__ */ new Map([
  ["rcap", 1],
  ["rch", 0.5],
  ["rem", 1],
  ["rex", 0.5],
  ["ric", 1],
  ["rlh", 1.2]
]);
var resolveLengthInPixels = (value, unit, opt = {}) => {
  const { dimension = {} } = opt;
  const { callback, em, rem: rem2, vh, vw } = dimension;
  if (isString(value)) {
    value = value.toLowerCase().trim();
    if (absoluteFontSize.has(value)) {
      return Number(absoluteFontSize.get(value)) * rem2;
    } else if (relativeFontSize.has(value)) {
      return Number(relativeFontSize.get(value)) * em;
    }
    return Number.NaN;
  } else if (Number.isFinite(value) && unit) {
    if (Object.hasOwn(dimension, unit)) {
      return value * Number(dimension[unit]);
    } else if (typeof callback === "function") {
      return value * callback(unit);
    } else if (absoluteLength.has(unit)) {
      return value * Number(absoluteLength.get(unit));
    } else if (relativeLength.has(unit)) {
      return value * Number(relativeLength.get(unit)) * rem2;
    } else if (relativeLength.has(`r${unit}`)) {
      return value * Number(relativeLength.get(`r${unit}`)) * em;
    } else {
      switch (unit) {
        case "vb":
        case "vi": {
          return value * vw;
        }
        case "vmax": {
          if (vh > vw) {
            return value * vh;
          }
          return value * vw;
        }
        case "vmin": {
          if (vh < vw) {
            return value * vh;
          }
          return value * vw;
        }
        default: {
          return Number.NaN;
        }
      }
    }
  }
  return Number.NaN;
};
var MAX_CACHE = 4096;
var CacheItem = class {
  /* private */
  #isNull;
  #item;
  /**
   * constructor
   */
  constructor(item, isNull = false) {
    this.#item = item;
    this.#isNull = !!isNull;
  }
  get item() {
    return this.#item;
  }
  get isNull() {
    return this.#isNull;
  }
};
var NullObject = class extends CacheItem {
  /**
   * constructor
   */
  constructor() {
    super(/* @__PURE__ */ Symbol("null"), true);
  }
};
var lruCache = new import_lru_cache.LRUCache({
  max: MAX_CACHE
});
var setCache = (key, value) => {
  if (key) {
    if (value === null) {
      lruCache.set(key, new NullObject());
    } else if (value instanceof CacheItem) {
      lruCache.set(key, value);
    } else {
      lruCache.set(key, new CacheItem(value));
    }
  }
};
var getCache = (key) => {
  if (key && lruCache.has(key)) {
    const item = lruCache.get(key);
    if (item instanceof CacheItem) {
      return item;
    }
    lruCache.delete(key);
    return false;
  }
  return false;
};
var createCacheKey = (keyData, opt = {}) => {
  const { customProperty = {}, dimension = {} } = opt;
  let cacheKey = "";
  if (keyData && Object.keys(keyData).length && typeof customProperty.callback !== "function" && typeof dimension.callback !== "function") {
    keyData.opt = valueToJsonString(opt);
    cacheKey = valueToJsonString(keyData);
  }
  return cacheKey;
};
var {
  CloseParen: PAREN_CLOSE4,
  Comment: COMMENT4,
  Dimension: DIM2,
  EOF: EOF4,
  Function: FUNC3,
  OpenParen: PAREN_OPEN3,
  Whitespace: W_SPACE4
} = import_css_tokenizer4.TokenType;
var NAMESPACE6 = "css-calc";
var TRIA2 = 3;
var HEX4 = 16;
var MAX_PCT3 = 100;
var REG_FN_CALC3 = new RegExp(SYN_FN_CALC);
var REG_FN_CALC_NUM = new RegExp(`^calc\\((${NUM})\\)$`);
var REG_FN_MATH_START2 = new RegExp(SYN_FN_MATH_START);
var REG_FN_VAR4 = new RegExp(SYN_FN_VAR);
var REG_FN_VAR_START = new RegExp(SYN_FN_VAR_START);
var REG_OPERATOR = /\s[*+/-]\s/;
var REG_TYPE_DIM = new RegExp(`^(${NUM})(${ANGLE}|${LENGTH})$`);
var REG_TYPE_DIM_PCT = new RegExp(`^(${NUM})(${ANGLE}|${LENGTH}|%)$`);
var REG_TYPE_PCT = new RegExp(`^(${NUM})%$`);
var Calculator = class {
  /* private */
  // number
  #hasNum;
  #numSum;
  #numMul;
  // percentage
  #hasPct;
  #pctSum;
  #pctMul;
  // dimension
  #hasDim;
  #dimSum;
  #dimSub;
  #dimMul;
  #dimDiv;
  // et cetra
  #hasEtc;
  #etcSum;
  #etcSub;
  #etcMul;
  #etcDiv;
  /**
   * constructor
   */
  constructor() {
    this.#hasNum = false;
    this.#numSum = [];
    this.#numMul = [];
    this.#hasPct = false;
    this.#pctSum = [];
    this.#pctMul = [];
    this.#hasDim = false;
    this.#dimSum = [];
    this.#dimSub = [];
    this.#dimMul = [];
    this.#dimDiv = [];
    this.#hasEtc = false;
    this.#etcSum = [];
    this.#etcSub = [];
    this.#etcMul = [];
    this.#etcDiv = [];
  }
  get hasNum() {
    return this.#hasNum;
  }
  set hasNum(value) {
    this.#hasNum = !!value;
  }
  get numSum() {
    return this.#numSum;
  }
  get numMul() {
    return this.#numMul;
  }
  get hasPct() {
    return this.#hasPct;
  }
  set hasPct(value) {
    this.#hasPct = !!value;
  }
  get pctSum() {
    return this.#pctSum;
  }
  get pctMul() {
    return this.#pctMul;
  }
  get hasDim() {
    return this.#hasDim;
  }
  set hasDim(value) {
    this.#hasDim = !!value;
  }
  get dimSum() {
    return this.#dimSum;
  }
  get dimSub() {
    return this.#dimSub;
  }
  get dimMul() {
    return this.#dimMul;
  }
  get dimDiv() {
    return this.#dimDiv;
  }
  get hasEtc() {
    return this.#hasEtc;
  }
  set hasEtc(value) {
    this.#hasEtc = !!value;
  }
  get etcSum() {
    return this.#etcSum;
  }
  get etcSub() {
    return this.#etcSub;
  }
  get etcMul() {
    return this.#etcMul;
  }
  get etcDiv() {
    return this.#etcDiv;
  }
  /**
   * clear values
   * @returns void
   */
  clear() {
    this.#hasNum = false;
    this.#numSum = [];
    this.#numMul = [];
    this.#hasPct = false;
    this.#pctSum = [];
    this.#pctMul = [];
    this.#hasDim = false;
    this.#dimSum = [];
    this.#dimSub = [];
    this.#dimMul = [];
    this.#dimDiv = [];
    this.#hasEtc = false;
    this.#etcSum = [];
    this.#etcSub = [];
    this.#etcMul = [];
    this.#etcDiv = [];
  }
  /**
   * sort values
   * @param values - values
   * @returns sorted values
   */
  sort(values = []) {
    const arr = [...values];
    if (arr.length > 1) {
      arr.sort((a3, b2) => {
        let res;
        if (REG_TYPE_DIM_PCT.test(a3) && REG_TYPE_DIM_PCT.test(b2)) {
          const [, valA, unitA] = a3.match(REG_TYPE_DIM_PCT);
          const [, valB, unitB] = b2.match(REG_TYPE_DIM_PCT);
          if (unitA === unitB) {
            if (Number(valA) === Number(valB)) {
              res = 0;
            } else if (Number(valA) > Number(valB)) {
              res = 1;
            } else {
              res = -1;
            }
          } else if (unitA > unitB) {
            res = 1;
          } else {
            res = -1;
          }
        } else {
          if (a3 === b2) {
            res = 0;
          } else if (a3 > b2) {
            res = 1;
          } else {
            res = -1;
          }
        }
        return res;
      });
    }
    return arr;
  }
  /**
   * multiply values
   * @returns resolved value
   */
  multiply() {
    const value = [];
    let num;
    if (this.#hasNum) {
      num = 1;
      for (const i3 of this.#numMul) {
        num *= i3;
        if (num === 0 || !Number.isFinite(num) || Number.isNaN(num)) {
          break;
        }
      }
      if (!this.#hasPct && !this.#hasDim && !this.hasEtc) {
        if (Number.isFinite(num)) {
          num = roundToPrecision(num, HEX4);
        }
        value.push(num);
      }
    }
    if (this.#hasPct) {
      if (typeof num !== "number") {
        num = 1;
      }
      for (const i3 of this.#pctMul) {
        num *= i3;
        if (num === 0 || !Number.isFinite(num) || Number.isNaN(num)) {
          break;
        }
      }
      if (Number.isFinite(num)) {
        num = `${roundToPrecision(num, HEX4)}%`;
      }
      if (!this.#hasDim && !this.hasEtc) {
        value.push(num);
      }
    }
    if (this.#hasDim) {
      let dim = "";
      let mul = "";
      let div = "";
      if (this.#dimMul.length) {
        if (this.#dimMul.length === 1) {
          [mul] = this.#dimMul;
        } else {
          mul = `${this.sort(this.#dimMul).join(" * ")}`;
        }
      }
      if (this.#dimDiv.length) {
        if (this.#dimDiv.length === 1) {
          [div] = this.#dimDiv;
        } else {
          div = `${this.sort(this.#dimDiv).join(" * ")}`;
        }
      }
      if (Number.isFinite(num)) {
        if (mul) {
          if (div) {
            if (div.includes("*")) {
              dim = (0, import_css_calc4.calc)(`calc(${num} * ${mul} / (${div}))`, {
                toCanonicalUnits: true
              });
            } else {
              dim = (0, import_css_calc4.calc)(`calc(${num} * ${mul} / ${div})`, {
                toCanonicalUnits: true
              });
            }
          } else {
            dim = (0, import_css_calc4.calc)(`calc(${num} * ${mul})`, {
              toCanonicalUnits: true
            });
          }
        } else if (div.includes("*")) {
          dim = (0, import_css_calc4.calc)(`calc(${num} / (${div}))`, {
            toCanonicalUnits: true
          });
        } else {
          dim = (0, import_css_calc4.calc)(`calc(${num} / ${div})`, {
            toCanonicalUnits: true
          });
        }
        value.push(dim.replace(/^calc/, ""));
      } else {
        if (!value.length && num !== void 0) {
          value.push(num);
        }
        if (mul) {
          if (div) {
            if (div.includes("*")) {
              dim = (0, import_css_calc4.calc)(`calc(${mul} / (${div}))`, {
                toCanonicalUnits: true
              });
            } else {
              dim = (0, import_css_calc4.calc)(`calc(${mul} / ${div})`, {
                toCanonicalUnits: true
              });
            }
          } else {
            dim = (0, import_css_calc4.calc)(`calc(${mul})`, {
              toCanonicalUnits: true
            });
          }
          if (value.length) {
            value.push("*", dim.replace(/^calc/, ""));
          } else {
            value.push(dim.replace(/^calc/, ""));
          }
        } else {
          dim = (0, import_css_calc4.calc)(`calc(${div})`, {
            toCanonicalUnits: true
          });
          if (value.length) {
            value.push("/", dim.replace(/^calc/, ""));
          } else {
            value.push("1", "/", dim.replace(/^calc/, ""));
          }
        }
      }
    }
    if (this.#hasEtc) {
      if (this.#etcMul.length) {
        if (!value.length && num !== void 0) {
          value.push(num);
        }
        const mul = this.sort(this.#etcMul).join(" * ");
        if (value.length) {
          value.push(`* ${mul}`);
        } else {
          value.push(`${mul}`);
        }
      }
      if (this.#etcDiv.length) {
        const div = this.sort(this.#etcDiv).join(" * ");
        if (div.includes("*")) {
          if (value.length) {
            value.push(`/ (${div})`);
          } else {
            value.push(`1 / (${div})`);
          }
        } else if (value.length) {
          value.push(`/ ${div}`);
        } else {
          value.push(`1 / ${div}`);
        }
      }
    }
    if (value.length) {
      return value.join(" ");
    }
    return "";
  }
  /**
   * sum values
   * @returns resolved value
   */
  sum() {
    const value = [];
    if (this.#hasNum) {
      let num = 0;
      for (const i3 of this.#numSum) {
        num += i3;
        if (!Number.isFinite(num) || Number.isNaN(num)) {
          break;
        }
      }
      value.push(num);
    }
    if (this.#hasPct) {
      let num = 0;
      for (const i3 of this.#pctSum) {
        num += i3;
        if (!Number.isFinite(num)) {
          break;
        }
      }
      if (Number.isFinite(num)) {
        num = `${num}%`;
      }
      if (value.length) {
        value.push(`+ ${num}`);
      } else {
        value.push(num);
      }
    }
    if (this.#hasDim) {
      let dim, sum, sub;
      if (this.#dimSum.length) {
        sum = this.sort(this.#dimSum).join(" + ");
      }
      if (this.#dimSub.length) {
        sub = this.sort(this.#dimSub).join(" + ");
      }
      if (sum) {
        if (sub) {
          if (sub.includes("-")) {
            dim = (0, import_css_calc4.calc)(`calc(${sum} - (${sub}))`, {
              toCanonicalUnits: true
            });
          } else {
            dim = (0, import_css_calc4.calc)(`calc(${sum} - ${sub})`, {
              toCanonicalUnits: true
            });
          }
        } else {
          dim = (0, import_css_calc4.calc)(`calc(${sum})`, {
            toCanonicalUnits: true
          });
        }
      } else {
        dim = (0, import_css_calc4.calc)(`calc(-1 * (${sub}))`, {
          toCanonicalUnits: true
        });
      }
      if (value.length) {
        value.push("+", dim.replace(/^calc/, ""));
      } else {
        value.push(dim.replace(/^calc/, ""));
      }
    }
    if (this.#hasEtc) {
      if (this.#etcSum.length) {
        const sum = this.sort(this.#etcSum).map((item) => {
          let res;
          if (REG_OPERATOR.test(item) && !item.startsWith("(") && !item.endsWith(")")) {
            res = `(${item})`;
          } else {
            res = item;
          }
          return res;
        }).join(" + ");
        if (value.length) {
          if (this.#etcSum.length > 1) {
            value.push(`+ (${sum})`);
          } else {
            value.push(`+ ${sum}`);
          }
        } else {
          value.push(`${sum}`);
        }
      }
      if (this.#etcSub.length) {
        const sub = this.sort(this.#etcSub).map((item) => {
          let res;
          if (REG_OPERATOR.test(item) && !item.startsWith("(") && !item.endsWith(")")) {
            res = `(${item})`;
          } else {
            res = item;
          }
          return res;
        }).join(" + ");
        if (value.length) {
          if (this.#etcSub.length > 1) {
            value.push(`- (${sub})`);
          } else {
            value.push(`- ${sub}`);
          }
        } else if (this.#etcSub.length > 1) {
          value.push(`-1 * (${sub})`);
        } else {
          value.push(`-1 * ${sub}`);
        }
      }
    }
    if (value.length) {
      return value.join(" ");
    }
    return "";
  }
};
var sortCalcValues = (values = [], finalize = false) => {
  if (values.length < TRIA2) {
    throw new Error(`Unexpected array length ${values.length}.`);
  }
  const start = values.shift();
  if (!isString(start) || !start.endsWith("(")) {
    throw new Error(`Unexpected token ${start}.`);
  }
  const end = values.pop();
  if (end !== ")") {
    throw new Error(`Unexpected token ${end}.`);
  }
  if (values.length === 1) {
    const [value] = values;
    if (!isStringOrNumber(value)) {
      throw new Error(`Unexpected token ${value}.`);
    }
    return `${start}${value}${end}`;
  }
  const sortedValues = [];
  const cal = new Calculator();
  let operator = "";
  const l2 = values.length;
  for (let i3 = 0; i3 < l2; i3++) {
    const value = values[i3];
    if (!isStringOrNumber(value)) {
      throw new Error(`Unexpected token ${value}.`);
    }
    if (value === "*" || value === "/") {
      operator = value;
    } else if (value === "+" || value === "-") {
      const sortedValue = cal.multiply();
      if (sortedValue) {
        sortedValues.push(sortedValue, value);
      }
      cal.clear();
      operator = "";
    } else {
      const numValue = Number(value);
      const strValue = `${value}`;
      switch (operator) {
        case "/": {
          if (Number.isFinite(numValue)) {
            cal.hasNum = true;
            cal.numMul.push(1 / numValue);
          } else if (REG_TYPE_PCT.test(strValue)) {
            const [, val] = strValue.match(REG_TYPE_PCT);
            cal.hasPct = true;
            cal.pctMul.push(MAX_PCT3 * MAX_PCT3 / Number(val));
          } else if (REG_TYPE_DIM.test(strValue)) {
            cal.hasDim = true;
            cal.dimDiv.push(strValue);
          } else {
            cal.hasEtc = true;
            cal.etcDiv.push(strValue);
          }
          break;
        }
        case "*":
        default: {
          if (Number.isFinite(numValue)) {
            cal.hasNum = true;
            cal.numMul.push(numValue);
          } else if (REG_TYPE_PCT.test(strValue)) {
            const [, val] = strValue.match(REG_TYPE_PCT);
            cal.hasPct = true;
            cal.pctMul.push(Number(val));
          } else if (REG_TYPE_DIM.test(strValue)) {
            cal.hasDim = true;
            cal.dimMul.push(strValue);
          } else {
            cal.hasEtc = true;
            cal.etcMul.push(strValue);
          }
        }
      }
    }
    if (i3 === l2 - 1) {
      const sortedValue = cal.multiply();
      if (sortedValue) {
        sortedValues.push(sortedValue);
      }
      cal.clear();
      operator = "";
    }
  }
  let resolvedValue = "";
  if (finalize && (sortedValues.includes("+") || sortedValues.includes("-"))) {
    const finalizedValues = [];
    cal.clear();
    operator = "";
    const l22 = sortedValues.length;
    for (let i3 = 0; i3 < l22; i3++) {
      const value = sortedValues[i3];
      if (isStringOrNumber(value)) {
        if (value === "+" || value === "-") {
          operator = value;
        } else {
          const numValue = Number(value);
          const strValue = `${value}`;
          switch (operator) {
            case "-": {
              if (Number.isFinite(numValue)) {
                cal.hasNum = true;
                cal.numSum.push(-1 * numValue);
              } else if (REG_TYPE_PCT.test(strValue)) {
                const [, val] = strValue.match(REG_TYPE_PCT);
                cal.hasPct = true;
                cal.pctSum.push(-1 * Number(val));
              } else if (REG_TYPE_DIM.test(strValue)) {
                cal.hasDim = true;
                cal.dimSub.push(strValue);
              } else {
                cal.hasEtc = true;
                cal.etcSub.push(strValue);
              }
              break;
            }
            case "+":
            default: {
              if (Number.isFinite(numValue)) {
                cal.hasNum = true;
                cal.numSum.push(numValue);
              } else if (REG_TYPE_PCT.test(strValue)) {
                const [, val] = strValue.match(REG_TYPE_PCT);
                cal.hasPct = true;
                cal.pctSum.push(Number(val));
              } else if (REG_TYPE_DIM.test(strValue)) {
                cal.hasDim = true;
                cal.dimSum.push(strValue);
              } else {
                cal.hasEtc = true;
                cal.etcSum.push(strValue);
              }
            }
          }
        }
      }
      if (i3 === l22 - 1) {
        const sortedValue = cal.sum();
        if (sortedValue) {
          finalizedValues.push(sortedValue);
        }
        cal.clear();
        operator = "";
      }
    }
    resolvedValue = finalizedValues.join(" ").replace(/\+\s-/g, "- ");
  } else {
    resolvedValue = sortedValues.join(" ").replace(/\+\s-/g, "- ");
  }
  if (resolvedValue.startsWith("(") && resolvedValue.endsWith(")") && resolvedValue.lastIndexOf("(") === 0 && resolvedValue.indexOf(")") === resolvedValue.length - 1) {
    resolvedValue = resolvedValue.replace(/^\(/, "").replace(/\)$/, "");
  }
  return `${start}${resolvedValue}${end}`;
};
var serializeCalc = (value, opt = {}) => {
  const { format = "" } = opt;
  if (isString(value)) {
    if (!REG_FN_VAR_START.test(value) || format !== VAL_SPEC) {
      return value;
    }
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE6,
      name: "serializeCalc",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const items = (0, import_css_tokenizer4.tokenize)({ css: value }).map((token) => {
    const [type, value2] = token;
    let res = "";
    if (type !== W_SPACE4 && type !== COMMENT4) {
      res = value2;
    }
    return res;
  }).filter((v) => v);
  let startIndex = items.findLastIndex((item) => /\($/.test(item));
  while (startIndex) {
    const endIndex = items.findIndex((item, index) => {
      return item === ")" && index > startIndex;
    });
    const slicedValues = items.slice(startIndex, endIndex + 1);
    let serializedValue = sortCalcValues(slicedValues);
    if (REG_FN_VAR_START.test(serializedValue)) {
      serializedValue = (0, import_css_calc4.calc)(serializedValue, {
        toCanonicalUnits: true
      });
    }
    items.splice(startIndex, endIndex - startIndex + 1, serializedValue);
    startIndex = items.findLastIndex((item) => /\($/.test(item));
  }
  const serializedCalc = sortCalcValues(items, true);
  setCache(cacheKey, serializedCalc);
  return serializedCalc;
};
var resolveDimension = (token, opt = {}) => {
  if (!Array.isArray(token)) {
    throw new TypeError(`${token} is not an array.`);
  }
  const [, , , , detail = {}] = token;
  const { unit, value } = detail;
  if (unit === "px") {
    return `${value}${unit}`;
  }
  const pixelValue = resolveLengthInPixels(Number(value), unit, opt);
  if (Number.isFinite(pixelValue)) {
    return `${roundToPrecision(pixelValue, HEX4)}px`;
  }
  return new NullObject();
};
var parseTokens2 = (tokens, opt = {}) => {
  if (!Array.isArray(tokens)) {
    throw new TypeError(`${tokens} is not an array.`);
  }
  const { format = "" } = opt;
  const mathFunc = /* @__PURE__ */ new Set();
  let nest = 0;
  const res = [];
  while (tokens.length) {
    const token = tokens.shift();
    if (!Array.isArray(token)) {
      throw new TypeError(`${token} is not an array.`);
    }
    const [type = "", value = ""] = token;
    switch (type) {
      case DIM2: {
        if (format === VAL_SPEC && !mathFunc.has(nest)) {
          res.push(value);
        } else {
          const resolvedValue = resolveDimension(token, opt);
          if (isString(resolvedValue)) {
            res.push(resolvedValue);
          } else {
            res.push(value);
          }
        }
        break;
      }
      case FUNC3:
      case PAREN_OPEN3: {
        res.push(value);
        nest++;
        if (REG_FN_MATH_START2.test(value)) {
          mathFunc.add(nest);
        }
        break;
      }
      case PAREN_CLOSE4: {
        if (res.length) {
          const lastValue = res[res.length - 1];
          if (lastValue === " ") {
            res.splice(-1, 1, value);
          } else {
            res.push(value);
          }
        } else {
          res.push(value);
        }
        if (mathFunc.has(nest)) {
          mathFunc.delete(nest);
        }
        nest--;
        break;
      }
      case W_SPACE4: {
        if (res.length) {
          const lastValue = res[res.length - 1];
          if (isString(lastValue) && !lastValue.endsWith("(") && lastValue !== " ") {
            res.push(value);
          }
        }
        break;
      }
      default: {
        if (type !== COMMENT4 && type !== EOF4) {
          res.push(value);
        }
      }
    }
  }
  return res;
};
var cssCalc = (value, opt = {}) => {
  const { format = "" } = opt;
  if (isString(value)) {
    if (REG_FN_VAR4.test(value)) {
      if (format === VAL_SPEC) {
        return value;
      } else {
        const resolvedValue2 = resolveVar(value, opt);
        if (isString(resolvedValue2)) {
          return resolvedValue2;
        } else {
          return "";
        }
      }
    } else if (!REG_FN_CALC3.test(value)) {
      return value;
    }
    value = value.toLowerCase().trim();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE6,
      name: "cssCalc",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const tokens = (0, import_css_tokenizer4.tokenize)({ css: value });
  const values = parseTokens2(tokens, opt);
  let resolvedValue = (0, import_css_calc4.calc)(values.join(""), {
    toCanonicalUnits: true
  });
  if (REG_FN_VAR_START.test(value)) {
    if (REG_TYPE_DIM_PCT.test(resolvedValue)) {
      const [, val, unit] = resolvedValue.match(
        REG_TYPE_DIM_PCT
      );
      resolvedValue = `${roundToPrecision(Number(val), HEX4)}${unit}`;
    }
    if (resolvedValue && !REG_FN_VAR_START.test(resolvedValue) && format === VAL_SPEC) {
      resolvedValue = `calc(${resolvedValue})`;
    }
  }
  if (format === VAL_SPEC) {
    if (/\s[-+*/]\s/.test(resolvedValue) && !resolvedValue.includes("NaN")) {
      resolvedValue = serializeCalc(resolvedValue, opt);
    } else if (REG_FN_CALC_NUM.test(resolvedValue)) {
      const [, val] = resolvedValue.match(REG_FN_CALC_NUM);
      resolvedValue = `calc(${roundToPrecision(Number(val), HEX4)})`;
    }
  }
  setCache(cacheKey, resolvedValue);
  return resolvedValue;
};
var NAMESPACE7 = "css-gradient";
var DIM_ANGLE = `${NUM}(?:${ANGLE})`;
var DIM_ANGLE_PCT = `${DIM_ANGLE}|${PCT}`;
var DIM_LEN = `${NUM}(?:${LENGTH})|0`;
var DIM_LEN_PCT = `${DIM_LEN}|${PCT}`;
var DIM_LEN_PCT_POSI = `${NUM_POSITIVE}(?:${LENGTH}|%)|0`;
var DIM_LEN_POSI = `${NUM_POSITIVE}(?:${LENGTH})|0`;
var CTR = "center";
var L_R = "left|right";
var T_B = "top|bottom";
var S_E = "start|end";
var AXIS_X = `${L_R}|x-(?:${S_E})`;
var AXIS_Y = `${T_B}|y-(?:${S_E})`;
var BLOCK = `block-(?:${S_E})`;
var INLINE = `inline-(?:${S_E})`;
var POS_1 = `${CTR}|${AXIS_X}|${AXIS_Y}|${BLOCK}|${INLINE}|${DIM_LEN_PCT}`;
var POS_2 = [
  `(?:${CTR}|${AXIS_X})\\s+(?:${CTR}|${AXIS_Y})`,
  `(?:${CTR}|${AXIS_Y})\\s+(?:${CTR}|${AXIS_X})`,
  `(?:${CTR}|${AXIS_X}|${DIM_LEN_PCT})\\s+(?:${CTR}|${AXIS_Y}|${DIM_LEN_PCT})`,
  `(?:${CTR}|${BLOCK})\\s+(?:${CTR}|${INLINE})`,
  `(?:${CTR}|${INLINE})\\s+(?:${CTR}|${BLOCK})`,
  `(?:${CTR}|${S_E})\\s+(?:${CTR}|${S_E})`
].join("|");
var POS_4 = [
  `(?:${AXIS_X})\\s+(?:${DIM_LEN_PCT})\\s+(?:${AXIS_Y})\\s+(?:${DIM_LEN_PCT})`,
  `(?:${AXIS_Y})\\s+(?:${DIM_LEN_PCT})\\s+(?:${AXIS_X})\\s+(?:${DIM_LEN_PCT})`,
  `(?:${BLOCK})\\s+(?:${DIM_LEN_PCT})\\s+(?:${INLINE})\\s+(?:${DIM_LEN_PCT})`,
  `(?:${INLINE})\\s+(?:${DIM_LEN_PCT})\\s+(?:${BLOCK})\\s+(?:${DIM_LEN_PCT})`,
  `(?:${S_E})\\s+(?:${DIM_LEN_PCT})\\s+(?:${S_E})\\s+(?:${DIM_LEN_PCT})`
].join("|");
var RAD_EXTENT = "(?:clos|farth)est-(?:corner|side)";
var RAD_SIZE = [
  `${RAD_EXTENT}(?:\\s+${RAD_EXTENT})?`,
  `${DIM_LEN_POSI}`,
  `(?:${DIM_LEN_PCT_POSI})\\s+(?:${DIM_LEN_PCT_POSI})`
].join("|");
var RAD_SHAPE = "circle|ellipse";
var FROM_ANGLE = `from\\s+${DIM_ANGLE}`;
var AT_POSITION = `at\\s+(?:${POS_1}|${POS_2}|${POS_4})`;
var TO_SIDE_CORNER = `to\\s+(?:(?:${L_R})(?:\\s(?:${T_B}))?|(?:${T_B})(?:\\s(?:${L_R}))?)`;
var IN_COLOR_SPACE = `in\\s+(?:${CS_RECT}|${CS_HUE})`;
var REG_GRAD = /^(?:repeating-)?(?:conic|linear|radial)-gradient\(/;
var REG_GRAD_CAPT = /^((?:repeating-)?(?:conic|linear|radial)-gradient)\(/;
var getGradientType = (value) => {
  if (isString(value)) {
    value = value.trim();
    if (REG_GRAD.test(value)) {
      const [, type] = value.match(REG_GRAD_CAPT);
      return type;
    }
  }
  return "";
};
var validateGradientLine = (value, type) => {
  if (isString(value) && isString(type)) {
    value = value.trim();
    type = type.trim();
    let lineSyntax = "";
    const defaultValues = [];
    if (/^(?:repeating-)?linear-gradient$/.test(type)) {
      lineSyntax = [
        `(?:${DIM_ANGLE}|${TO_SIDE_CORNER})(?:\\s+${IN_COLOR_SPACE})?`,
        `${IN_COLOR_SPACE}(?:\\s+(?:${DIM_ANGLE}|${TO_SIDE_CORNER}))?`
      ].join("|");
      defaultValues.push(/to\s+bottom/);
    } else if (/^(?:repeating-)?radial-gradient$/.test(type)) {
      lineSyntax = [
        `(?:${RAD_SHAPE})(?:\\s+(?:${RAD_SIZE}))?(?:\\s+${AT_POSITION})?(?:\\s+${IN_COLOR_SPACE})?`,
        `(?:${RAD_SIZE})(?:\\s+(?:${RAD_SHAPE}))?(?:\\s+${AT_POSITION})?(?:\\s+${IN_COLOR_SPACE})?`,
        `${AT_POSITION}(?:\\s+${IN_COLOR_SPACE})?`,
        `${IN_COLOR_SPACE}(?:\\s+${RAD_SHAPE})(?:\\s+(?:${RAD_SIZE}))?(?:\\s+${AT_POSITION})?`,
        `${IN_COLOR_SPACE}(?:\\s+${RAD_SIZE})(?:\\s+(?:${RAD_SHAPE}))?(?:\\s+${AT_POSITION})?`,
        `${IN_COLOR_SPACE}(?:\\s+${AT_POSITION})?`
      ].join("|");
      defaultValues.push(/ellipse/, /farthest-corner/, /at\s+center/);
    } else if (/^(?:repeating-)?conic-gradient$/.test(type)) {
      lineSyntax = [
        `${FROM_ANGLE}(?:\\s+${AT_POSITION})?(?:\\s+${IN_COLOR_SPACE})?`,
        `${AT_POSITION}(?:\\s+${IN_COLOR_SPACE})?`,
        `${IN_COLOR_SPACE}(?:\\s+${FROM_ANGLE})?(?:\\s+${AT_POSITION})?`
      ].join("|");
      defaultValues.push(/at\s+center/);
    }
    if (lineSyntax) {
      const reg = new RegExp(`^(?:${lineSyntax})$`);
      const valid = reg.test(value);
      if (valid) {
        let line = value;
        for (const defaultValue of defaultValues) {
          line = line.replace(defaultValue, "");
        }
        line = line.replace(/\s{2,}/g, " ").trim();
        return {
          line,
          valid
        };
      }
      return {
        valid,
        line: value
      };
    }
  }
  return {
    line: value,
    valid: false
  };
};
var validateColorStopList = (list, type, opt = {}) => {
  if (Array.isArray(list) && list.length > 1) {
    const dimension = /^(?:repeating-)?conic-gradient$/.test(type) ? DIM_ANGLE_PCT : DIM_LEN_PCT;
    const regColorHint = new RegExp(`^(?:${dimension})$`);
    const regDimension = new RegExp(`(?:\\s+(?:${dimension})){1,2}$`);
    const valueTypes = [];
    const valueList = [];
    for (const item of list) {
      if (isString(item)) {
        if (regColorHint.test(item)) {
          valueTypes.push("hint");
          valueList.push(item);
        } else {
          const itemColor = item.replace(regDimension, "");
          if (isColor(itemColor, { format: VAL_SPEC })) {
            const resolvedColor = resolveColor(itemColor, opt);
            valueTypes.push("color");
            valueList.push(item.replace(itemColor, resolvedColor));
          } else {
            return {
              colorStops: list,
              valid: false
            };
          }
        }
      }
    }
    const valid = /^color(?:,(?:hint,)?color)+$/.test(valueTypes.join(","));
    return {
      valid,
      colorStops: valueList
    };
  }
  return {
    colorStops: list,
    valid: false
  };
};
var parseGradient = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
    const cacheKey = createCacheKey(
      {
        namespace: NAMESPACE7,
        name: "parseGradient",
        value
      },
      opt
    );
    const cachedResult = getCache(cacheKey);
    if (cachedResult instanceof CacheItem) {
      if (cachedResult.isNull) {
        return null;
      }
      return cachedResult.item;
    }
    const type = getGradientType(value);
    const gradValue = value.replace(REG_GRAD, "").replace(/\)$/, "");
    if (type && gradValue) {
      const [lineOrColorStop = "", ...itemList] = splitValue(gradValue, {
        delimiter: ","
      });
      const dimension = /^(?:repeating-)?conic-gradient$/.test(type) ? DIM_ANGLE_PCT : DIM_LEN_PCT;
      const regDimension = new RegExp(`(?:\\s+(?:${dimension})){1,2}$`);
      let colorStop = "";
      if (regDimension.test(lineOrColorStop)) {
        const itemColor = lineOrColorStop.replace(regDimension, "");
        if (isColor(itemColor, { format: VAL_SPEC })) {
          const resolvedColor = resolveColor(itemColor, opt);
          colorStop = lineOrColorStop.replace(itemColor, resolvedColor);
        }
      } else if (isColor(lineOrColorStop, { format: VAL_SPEC })) {
        colorStop = resolveColor(lineOrColorStop, opt);
      }
      if (colorStop) {
        itemList.unshift(colorStop);
        const { colorStops, valid } = validateColorStopList(
          itemList,
          type,
          opt
        );
        if (valid) {
          const res = {
            value,
            type,
            colorStopList: colorStops
          };
          setCache(cacheKey, res);
          return res;
        }
      } else if (itemList.length > 1) {
        const { line: gradientLine, valid: validLine } = validateGradientLine(
          lineOrColorStop,
          type
        );
        const { colorStops, valid: validColorStops } = validateColorStopList(
          itemList,
          type,
          opt
        );
        if (validLine && validColorStops) {
          const res = {
            value,
            type,
            gradientLine,
            colorStopList: colorStops
          };
          setCache(cacheKey, res);
          return res;
        }
      }
    }
    setCache(cacheKey, null);
    return null;
  }
  return null;
};
var resolveGradient = (value, opt = {}) => {
  const { format = VAL_COMP } = opt;
  const gradient = parseGradient(value, opt);
  if (gradient) {
    const { type = "", gradientLine = "", colorStopList = [] } = gradient;
    if (type && Array.isArray(colorStopList) && colorStopList.length > 1) {
      if (gradientLine) {
        return `${type}(${gradientLine}, ${colorStopList.join(", ")})`;
      }
      return `${type}(${colorStopList.join(", ")})`;
    }
  }
  if (format === VAL_SPEC) {
    return "";
  }
  return "none";
};
var isGradient = (value, opt = {}) => {
  const gradient = parseGradient(value, opt);
  return gradient !== null;
};
var NAMESPACE8 = "convert";
var REG_FN_CALC4 = new RegExp(SYN_FN_CALC);
var REG_FN_REL3 = new RegExp(SYN_FN_REL);
var REG_FN_VAR5 = new RegExp(SYN_FN_VAR);
var preProcess = (value, opt = {}) => {
  if (isString(value)) {
    value = value.trim();
    if (!value) {
      return new NullObject();
    }
  } else {
    return new NullObject();
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "preProcess",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return cachedResult;
    }
    return cachedResult.item;
  }
  if (REG_FN_VAR5.test(value)) {
    const resolvedValue = resolveVar(value, opt);
    if (isString(resolvedValue)) {
      value = resolvedValue;
    } else {
      setCache(cacheKey, null);
      return new NullObject();
    }
  }
  if (REG_FN_REL3.test(value)) {
    const resolvedValue = resolveRelativeColor(value, opt);
    if (isString(resolvedValue)) {
      value = resolvedValue;
    } else {
      setCache(cacheKey, null);
      return new NullObject();
    }
  } else if (REG_FN_CALC4.test(value)) {
    value = cssCalc(value, opt);
  }
  if (value.startsWith("color-mix")) {
    const clonedOpt = structuredClone(opt);
    clonedOpt.format = VAL_COMP;
    clonedOpt.nullable = true;
    const resolvedValue = resolveColor(value, clonedOpt);
    setCache(cacheKey, resolvedValue);
    return resolvedValue;
  }
  setCache(cacheKey, value);
  return value;
};
var numberToHex = (value) => {
  const hex2 = numberToHexString(value);
  return hex2;
};
var colorToHex = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return null;
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const { alpha: alpha2 = false } = opt;
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToHex",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    if (cachedResult.isNull) {
      return null;
    }
    return cachedResult.item;
  }
  let hex2;
  opt.nullable = true;
  if (alpha2) {
    opt.format = "hexAlpha";
    hex2 = resolveColor(value, opt);
  } else {
    opt.format = "hex";
    hex2 = resolveColor(value, opt);
  }
  if (isString(hex2)) {
    setCache(cacheKey, hex2);
    return hex2;
  }
  setCache(cacheKey, null);
  return null;
};
var colorToHsl = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToHsl",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  opt.format = "hsl";
  const hsl2 = convertColorToHsl(value, opt);
  setCache(cacheKey, hsl2);
  return hsl2;
};
var colorToHwb = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToHwb",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  opt.format = "hwb";
  const hwb = convertColorToHwb(value, opt);
  setCache(cacheKey, hwb);
  return hwb;
};
var colorToLab = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToLab",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const lab2 = convertColorToLab(value, opt);
  setCache(cacheKey, lab2);
  return lab2;
};
var colorToLch = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToLch",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const lch2 = convertColorToLch(value, opt);
  setCache(cacheKey, lch2);
  return lch2;
};
var colorToOklab = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToOklab",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const lab2 = convertColorToOklab(value, opt);
  setCache(cacheKey, lab2);
  return lab2;
};
var colorToOklch = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToOklch",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const lch2 = convertColorToOklch(value, opt);
  setCache(cacheKey, lch2);
  return lch2;
};
var colorToRgb = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToRgb",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  const rgb2 = convertColorToRgb(value, opt);
  setCache(cacheKey, rgb2);
  return rgb2;
};
var colorToXyz = (value, opt = {}) => {
  if (isString(value)) {
    const resolvedValue = preProcess(value, opt);
    if (resolvedValue instanceof NullObject) {
      return [0, 0, 0, 0];
    }
    value = resolvedValue.toLowerCase();
  } else {
    throw new TypeError(`${value} is not a string.`);
  }
  const cacheKey = createCacheKey(
    {
      namespace: NAMESPACE8,
      name: "colorToXyz",
      value
    },
    opt
  );
  const cachedResult = getCache(cacheKey);
  if (cachedResult instanceof CacheItem) {
    return cachedResult.item;
  }
  let xyz;
  if (value.startsWith("color(")) {
    [, ...xyz] = parseColorFunc(value, opt);
  } else {
    [, ...xyz] = parseColorValue(value, opt);
  }
  setCache(cacheKey, xyz);
  return xyz;
};
var colorToXyzD50 = (value, opt = {}) => {
  opt.d50 = true;
  return colorToXyz(value, opt);
};
var convert = {
  colorToHex,
  colorToHsl,
  colorToHwb,
  colorToLab,
  colorToLch,
  colorToOklab,
  colorToOklch,
  colorToRgb,
  colorToXyz,
  colorToXyzD50,
  numberToHex
};
var utils = {
  cssCalc,
  cssVar,
  extractDashedIdent,
  isColor,
  isGradient,
  resolveGradient,
  resolveLengthInPixels,
  splitValue
};
/*! Bundled license information:

@csstools/color-helpers/dist/index.mjs:
  (**
   * Convert an array of a98-rgb values in the range 0.0 - 1.0
   * to linear light (un-companded) form. Negative values are also now accepted
   *
   * @license W3C https://www.w3.org/Consortium/Legal/2015/copyright-software-and-document
   * @copyright This software or document includes material copied from or derived from https://github.com/w3c/csswg-drafts/blob/main/css-color-4/conversions.js. Copyright © 2022 W3C® (MIT, ERCIM, Keio, Beihang).
   *)
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

@asamuzakjp/css-color/dist/cjs/index.cjs:
  (*!
   * CSS color - Resolve, parse, convert CSS color.
   * @license MIT
   * @copyright asamuzaK (Kazz)
   * @see {@link https://github.com/asamuzaK/cssColor/blob/main/LICENSE}
   *)
*/
