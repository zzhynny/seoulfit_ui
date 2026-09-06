import 'package:flutter/material.dart';

import 'app_colors.dart';

/// Tourism and shopping category colours, carried over verbatim from the
/// Flutter app's theme.
///
/// These are **not** part of the SeoulFit palette and must not be restyled to
/// match it. Each value was chosen so a numeral stays legible inside a map
/// marker — the app's theme records the measured contrast ratios (shopping:
/// SP 4.47 / TM 3.56 / MO 3.68 / DS 6.29 / DF 5.38 / SW 4.99) — and mint is
/// deliberately absent from both maps because the "my location" dot uses it,
/// so a category sharing it would be indistinguishable from the user.
///
/// The two maps use disjoint codes and could be merged, but they are
/// different axes (tourism vs shopping); adjusting one must not drag the
/// other along.

/// Korea Tourism Organization `lclsSystm1` categories.
const kCategoryColors = <String, Color>{
  'VE': Color(0xFF7C3AED), // Culture — violet
  'EX': Color(0xFFF59E0B), // Experience — amber
  'HS': Color(0xFFE63946), // History — persimmon
  'NA': Color(0xFF10B981), // Nature — green
  'LS': Color(0xFFDB2777), // Leisure — magenta
  'AC': Color(0xFF457B9D), // Stay — sky blue
};

/// Visit Seoul shopping sub-categories.
const kShoppingColors = <String, Color>{
  'SP': Color(0xFF6366F1), // Shops — indigo
  'TM': Color(0xFFEA580C), // Traditional markets — terracotta
  'MO': Color(0xFF0891B2), // Malls & outlets — cyan
  'DS': Color(0xFFBE123C), // Department stores — rose
  'DF': Color(0xFF9333EA), // Duty free — purple
  'SW': Color(0xFF4D7C0F), // Supermarkets — olive
};

/// Short labels for chips and sheets. 1:1 with the backend codes.
const kShoppingNames = <String, String>{
  'SP': 'Shops',
  'TM': 'Markets',
  'MO': 'Malls',
  'DS': 'Dept stores',
  'DF': 'Duty free',
  'SW': 'Supermarkets',
};

Color categoryColor(String category) =>
    kCategoryColors[category] ?? AppColors.textSecondary;

/// Text colour to lay over [categoryColor]. Amber and green fail white-text
/// contrast (2.15 / 2.54), so those two take ink instead (6.87 / 5.82).
Color categoryFg(String category) =>
    category == 'EX' || category == 'NA'
        ? AppColors.textPrimary
        : AppColors.surface;

Color shoppingColor(String category) =>
    kShoppingColors[category] ?? AppColors.textSecondary;
