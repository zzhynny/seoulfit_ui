import 'package:flutter/material.dart';

import '../theme/theme.dart';

/// Attribution for the open data this screen shows.
///
/// The Korea Tourism Organization's public-data terms require the source to be
/// named wherever its data is displayed, as text — their CI/BI artwork may not
/// be reproduced, and naming the API product alone ("TourAPI") does not count.
///
/// Both spellings are given because the app's UI is English but the required
/// form is registered in Korean.
class DataSourceNote extends StatelessWidget {
  const DataSourceNote({super.key, this.source = DataSource.koreaTourism});

  final DataSource source;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.md),
      child: Text(
        'Source: ⓒ ${source.label}',
        style: AppTextStyles.caption.copyWith(color: AppColors.textSecondary),
      ),
    );
  }
}

enum DataSource {
  koreaTourism('Korea Tourism Organization (한국관광공사)'),
  seoulTourism('Seoul Tourism Organization (서울관광재단)');

  const DataSource(this.label);
  final String label;
}
