import 'package:flutter/material.dart';
import '../../models/lens.dart';
import '../../theme/theme.dart';

class LensResultScreen extends StatelessWidget {
  const LensResultScreen({super.key, required this.result, required this.onScanAnother});

  final LensPlaceResult result;
  final VoidCallback onScanAnother;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Stack(
            children: [
              SizedBox(
                height: 320,
                width: double.infinity,
                child: Image.asset('assets/images/lens-result-hero.png', fit: BoxFit.cover),
              ),
              Container(height: 320, color: Colors.black.withValues(alpha: 0.15)),
              Positioned(
                left: 24,
                right: 24,
                top: 8,
                child: Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15), borderRadius: BorderRadius.circular(30)),
                      child: Text('📷 Seoul Lens', style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.1),
                        border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                        borderRadius: BorderRadius.circular(30),
                      ),
                      child: Text('Seoul Open Data', style: AppTextStyles.caption.copyWith(color: Colors.white.withValues(alpha: 0.9))),
                    ),
                  ],
                ),
              ),
              Positioned(
                left: 24,
                bottom: 24,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.75),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: RichText(
                    text: TextSpan(
                      style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w600),
                      children: [
                        TextSpan(text: '📍 ${result.name} · '),
                        TextSpan(
                          text: '${result.confidence}% confidence',
                          style: const TextStyle(color: AppColors.primary, fontWeight: FontWeight.w700),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
          Container(
            width: double.infinity,
            decoration: const BoxDecoration(
              color: AppColors.composerBackground,
              borderRadius: BorderRadius.only(topLeft: Radius.circular(20), topRight: Radius.circular(20)),
            ),
            padding: const EdgeInsets.fromLTRB(16, 20, 16, 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(result.name, style: AppTextStyles.headingMedium.copyWith(fontSize: 24)),
                          Text(result.address, style: AppTextStyles.bodySmall),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(color: const Color(0xFFE8EFEB), borderRadius: BorderRadius.circular(12)),
                      child: Text('✓ VERIFIED', style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700)),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: AppColors.composerBackground,
                    border: Border.all(color: AppColors.borderAlt),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Column(
                    children: [
                      _infoRow('🕒', 'HOURS', result.hours),
                      _infoRow('📅', 'OPEN', result.openDays),
                      _infoRow('🗓️', 'CLOSED', result.closedNote),
                      _infoRow('🚇', 'GETTING THERE', result.gettingThere, isLast: true),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final tag in result.hashtags)
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                        decoration: BoxDecoration(
                          color: const Color(0xFFE8EFEB),
                          border: Border.all(color: AppColors.primary),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(tag, style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600)),
                      ),
                  ],
                ),
                const SizedBox(height: 16),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: AppColors.composerBackground,
                    border: Border.all(color: AppColors.borderAlt),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        result.audioGuideCategory.toUpperCase(),
                        style: AppTextStyles.headingSmall.copyWith(fontSize: 11, color: AppColors.primary),
                      ),
                      const SizedBox(height: 4),
                      Text(result.audioGuideTitle, style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
                      const SizedBox(height: 8),
                      Text(result.audioGuideExcerpt, style: AppTextStyles.bodySmall),
                      const SizedBox(height: 14),
                      SizedBox(
                        width: double.infinity,
                        height: 48,
                        child: ElevatedButton.icon(
                          onPressed: () {},
                          icon: const Icon(Icons.play_arrow, size: 18, color: Colors.white),
                          label: Text('Play Audio', style: AppTextStyles.bodyMedium.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppColors.primary,
                            elevation: 0,
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: OutlinedButton(
                    onPressed: onScanAnother,
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: AppColors.primary),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
                    ),
                    child: Text('📷 Scan Another Place', style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700)),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String emoji, String label, String value, {bool isLast = false}) {
    return Container(
      decoration: BoxDecoration(
        border: isLast ? null : const Border(bottom: BorderSide(color: AppColors.borderAlt)),
      ),
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 24, child: Text(emoji, style: const TextStyle(fontSize: 18))),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(value, style: AppTextStyles.bodySmall),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
