using BroMakerLib;
using BroMakerLib.CustomObjects.Bros;
using UnityEngine;

namespace Bro_Template
{
    [HeroPreset( "Bro Template", HeroType.Rambro )]
    public class BroTemplate : CustomHero
    {
        // General

        // Primary

        // Melee

        // Special

        #region General
        protected override void Start()
        {
            useCustomMelee = true;

            base.Start();
        }

        protected override void Update()
        {
            base.Update();
            // Don't run any code past this point if the character is dead
            if ( acceptedDeath )
            {
                return;
            }
        }
        #endregion

        #region Primary
        #endregion

        #region Melee
        protected override void StartCustomMelee()
        {
            if ( CanStartNewMelee() )
            {
                frame = 1;
                counter = -0.05f;
                AnimateMelee();
            }
            else if ( CanStartMeleeFollowUp() )
            {
                meleeFollowUp = true;
            }

            if ( !jumpingMelee )
            {
                dashingMelee = true;
                xI = (float)Direction * speed;
            }

            StartMeleeCommon();
        }

        protected override void AnimateCustomMelee()
        {
            AnimateMeleeCommon();
            int num = 25 + Mathf.Clamp( frame, 0, 6 );
            int num2 = 1;
            if ( !standingMelee )
            {
                if ( jumpingMelee )
                {
                    num = 17 + Mathf.Clamp( frame, 0, 6 );
                    num2 = 6;
                }
                else if ( dashingMelee )
                {
                    num = 17 + Mathf.Clamp( frame, 0, 6 );
                    num2 = 6;
                    if ( frame == 4 )
                    {
                        counter -= 0.0334f;
                    }
                    else if ( frame == 5 )
                    {
                        counter -= 0.0334f;
                    }
                }
            }

            sprite.SetLowerLeftPixel( (float)( num * spritePixelWidth ), (float)( num2 * spritePixelHeight ) );
            if ( frame == 3 )
            {
                counter -= 0.066f;
                PerformKnifeMeleeAttack( true, true );
            }
            else if ( frame > 3 && !meleeHasHit )
            {
                PerformKnifeMeleeAttack( false, false );
            }

            if ( frame >= 6 )
            {
                frame = 0;
                CancelMelee();
            }
        }

        protected override void RunCustomMeleeMovement()
        {
            if ( !useNewKnifingFrames )
            {
                if ( Y > groundHeight + 1f )
                {
                    ApplyFallingGravity();
                }
            }
            else if ( jumpingMelee )
            {
                ApplyFallingGravity();
                if ( yI < maxFallSpeed )
                {
                    yI = maxFallSpeed;
                }
            }
            else if ( dashingMelee )
            {
                if ( frame <= 1 )
                {
                    xI = 0f;
                    yI = 0f;
                }
                else if ( frame <= 3 )
                {
                    if ( meleeChosenUnit == null )
                    {
                        if ( !isInQuicksand )
                        {
                            xI = speed * 1f * transform.localScale.x;
                        }
                        yI = 0f;
                    }
                    else if ( !isInQuicksand )
                    {
                        xI = speed * 0.5f * transform.localScale.x + ( meleeChosenUnit.X - X ) * 6f;
                    }
                }
                else if ( frame <= 5 )
                {
                    if ( !isInQuicksand )
                    {
                        xI = speed * 0.3f * transform.localScale.x;
                    }
                    ApplyFallingGravity();
                }
                else
                {
                    ApplyFallingGravity();
                }
            }
            else if ( Y > groundHeight + 1f )
            {
                CancelMelee();
            }
        }
        #endregion

        #region Special
        #endregion
    }
}
