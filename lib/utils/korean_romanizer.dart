/// Best-effort Revised Romanization of Korean text, syllable by syllable via
/// Unicode Hangul Syllable block arithmetic (U+AC00–U+D7A3).
///
/// ponytail: no cross-syllable assimilation (e.g. ㄹ+ㄹ→ll, 받침+ㄹ liaison,
/// or hyphenating administrative suffixes like -gu/-ro). Output is readable
/// but won't always match the official spelling on an embassy's own site.
/// Upgrade to a full RR ruleset if exact spelling starts to matter.
library;

const _lead = [
  'g', 'kk', 'n', 'd', 'tt', 'r', 'm', 'b', 'pp', 's', //
  'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h',
];

const _vowel = [
  'a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', //
  'wae', 'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu', 'eu', 'ui', 'i',
];

const _tail = [
  '', 'k', 'k', 'k', 'n', 'n', 'n', 't', 'l', 'k', //
  'm', 'l', 'l', 'l', 'p', 'l', 'm', 'p', 'p', 't', //
  't', 'ng', 't', 't', 'k', 't', 'p', 't',
];

String romanizeKorean(String input) {
  final buf = StringBuffer();
  var capitalizeNext = true;
  for (final rune in input.runes) {
    if (rune >= 0xAC00 && rune <= 0xD7A3) {
      final offset = rune - 0xAC00;
      final lead = offset ~/ (21 * 28);
      final vowel = (offset ~/ 28) % 21;
      final tail = offset % 28;
      var syllable = _lead[lead] + _vowel[vowel] + _tail[tail];
      if (capitalizeNext && syllable.isNotEmpty) {
        syllable = syllable[0].toUpperCase() + syllable.substring(1);
      }
      capitalizeNext = false;
      buf.write(syllable);
    } else {
      final ch = String.fromCharCode(rune);
      buf.write(ch);
      capitalizeNext = ch == ' ' || ch == ',' || ch == '-';
    }
  }
  return buf.toString();
}
