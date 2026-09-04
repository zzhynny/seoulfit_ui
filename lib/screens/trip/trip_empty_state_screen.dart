import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class TripEmptyStateScreen extends StatelessWidget {
  const TripEmptyStateScreen({super.key, required this.onStartPlanning});

  final VoidCallback onStartPlanning;

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    return Column(
      children: [
        Expanded(
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 200,
                  height: 207,
                  child: Image.asset(companion.lostMapAsset, fit: BoxFit.contain),
                ),
                const SizedBox(height: 16),
                Text('No travel plan yet!', style: AppTextStyles.headingMedium.copyWith(fontSize: 24)),
                const SizedBox(height: 8),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Text(
                    'Chat with our AI buddy to craft your personalized Seoul itinerary in seconds.',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
          child: PrimaryButton(label: 'Start Planning with AI', onPressed: onStartPlanning),
        ),
      ],
    );
  }
}
