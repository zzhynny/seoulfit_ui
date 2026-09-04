import 'package:flutter/material.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class StampBookOptInScreen extends StatefulWidget {
  const StampBookOptInScreen({
    super.key,
    required this.onStartCollecting,
    required this.onSkip,
  });

  final void Function(bool enabled) onStartCollecting;
  final VoidCallback onSkip;

  @override
  State<StampBookOptInScreen> createState() => _StampBookOptInScreenState();
}

class _StampBookOptInScreenState extends State<StampBookOptInScreen> {
  bool _enabled = true;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
          child: Row(
            children: [
              Image.asset(
                'assets/images/stamp-paw-green.png',
                width: 30,
                height: 30,
                fit: BoxFit.contain,
              ),
              const SizedBox(width: 12),
              Text('SeoulFit', style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
            ],
          ),
        ),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
            child: Column(
              children: [
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: AppColors.border),
                    borderRadius: BorderRadius.circular(24),
                  ),
                  child: Column(
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                            decoration: BoxDecoration(color: AppColors.chipBackground, borderRadius: BorderRadius.circular(6)),
                            child: Text('MY STAMP BOOK', style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700)),
                          ),
                          Text('Oct 12 - Oct 16', style: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w600)),
                        ],
                      ),
                      const SizedBox(height: 20),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          _stampColumn('assets/images/stamp-paw-green.png', 'Gyeongbokgung', 'Oct 12'),
                          _stampColumn('assets/images/stamp-paw-green.png', 'Cha-Teul', 'Oct 12'),
                          _stampColumn('assets/images/stamp-paw-empty.png', 'Next Spot', null),
                        ],
                      ),
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 16),
                        child: Divider(height: 1, color: AppColors.border),
                      ),
                      Row(
                        children: [
                          const Icon(Icons.auto_awesome, size: 16, color: AppColors.primary),
                          const SizedBox(width: 8),
                          Text('1/5 Days Stamped', style: AppTextStyles.bodySmall.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600)),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  'Collect stamps as you travel and get a summary card at the end of your trip?',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.headingMedium.copyWith(fontSize: 26),
                ),
                const SizedBox(height: 12),
                Text(
                  'Check in at places you visit to collect stamps. See your stamp book once your trip is complete.',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                ),
                const SizedBox(height: 16),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: AppColors.border),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Collect Stamps', style: AppTextStyles.cardTitle),
                          Text('Turn on this feature', style: AppTextStyles.bodySmall),
                        ],
                      ),
                      Switch(
                        value: _enabled,
                        onChanged: (v) => setState(() => _enabled = v),
                        activeThumbColor: Colors.white,
                        activeTrackColor: AppColors.primary,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: Column(
            children: [
              PrimaryButton(label: 'Start Collecting', onPressed: () => widget.onStartCollecting(_enabled)),
              TextButton(
                onPressed: widget.onSkip,
                child: Text(
                  "No thanks, I'll just travel",
                  style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary, fontWeight: FontWeight.w600, decoration: TextDecoration.underline),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _stampColumn(String asset, String label, String? date) {
    return Column(
      children: [
        Image.asset(asset, width: 68, height: 68, fit: BoxFit.contain),
        const SizedBox(height: 8),
        Text(label, style: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w700)),
        if (date != null) Text(date, style: AppTextStyles.caption),
      ],
    );
  }
}
