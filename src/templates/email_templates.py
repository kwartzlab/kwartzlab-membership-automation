from dataclasses import dataclass

"""
Use something like https://html5-editor.net/ to see and edit the format of the email in a more human way.
"""

MEMBERSHIP_TEAM_SIGNATURE: str = """
<b>Membership Team</b><br/>
Kwartzlab
"""

CUSTOM_SIGNATURE: str = """
<b>{signature_name}</b><br/>
{signature_role_block}
Kwartzlab
"""

@dataclass
class Email:
    subject: str | None
    body: str


RETURN_EMAIL = Email(
    subject="Kwartzlab Application return request",
    body="""
            <p>Hi {name},</p>

            <p>
                Thanks again for taking the time to apply and visit our space! It was great
                getting to know you.
            </p>

            <p>
                As we mentioned during your interview, we like to gather feedback from our
                community before moving forward with applications. This time, we didn’t
                receive enough responses to proceed just yet—but we’d love to give you another
                chance to connect with more people!
            </p>

            <p>
                You’re welcome to drop by another open house <b>(Tuesdays from 7–10 PM or the
                first Saturday of the month from 1–4 PM).</b> There’s no need for another
                interview—just an opportunity to meet more people so they can provide input
                on your application.
            </p>

            <p>
                Let us know if you have any questions, and we hope to see you again soon!
            </p>
        """
)

ACCEPTANCE_EMAIL: str = Email(
    subject="Kwartzlab Welcome Email",
    body="""
            <p>Hey {name}!</p> 

            <p>Your application was successful! We are so excited to welcome you to join KwartzLab.</p>

            <p><strong>Next steps:</strong></p>

            <ol>
            <li>
                Please pay your
                <a href="https://www.kwartzlab.ca/membership-dues/">member dues</a>
                <strong>before</strong> coming in for your new membership tour.
            </li>
            <li>
                Visit us during a Tuesday Open Night to pick up your fob and complete a new member tour.
                <ol style="margin-top: 6px;">
                <li>
                    <span style="color:rgb(0,0,255);background-color:transparent;font-weight:700;">
                        New member tours start at 8pm 
                    </span>, but we open at 7pm if you'd like to come meet people.
                </li>
                <li>
                    If you cannot make it on a Tuesday, let me know and I’ll try to schedule an alternative time for you.
                </li>
                </ol>
            </li>
            <li>
                <span style="color:rgb(0,0,255);background-color:transparent;font-weight:700;">
                Let me know when you're coming
                </span>
                so we can ensure there's a suitable member available to help you when you arrive.
            </li>
            </ol>

            <p><strong>Some important links:</strong></p>

            <ul>
            <li>How to pay your <a href="https://www.kwartzlab.ca/membership-dues/">member dues</a></li>
            <li>The <a href="https://www.kwartzlab.ca/areas">New Member Tour</a> page</li>
            <li><a href="https://drive.google.com/file/d/1fyYgTGRiWLfQ_FXas3FKzsQnG-7EwSkz/view">Getting Started with Slack: A guide for new users</a></li>
            <li><a href="https://drive.google.com/file/d/1_b7cxM8HNnGRMcSfWCe69BuNP-8uk-nu/view">Code of Conduct</a></li>
            <li><a href="https://drive.google.com/file/d/1YxkSEWCCSFS7REHvKnNh8axgKmc8SZK6/view">Other Policies and Procedure</a></li>
            </ul>

            <p>If you have any questions, don't hesitate to reach out.</p>
        """
)

HIATUS_SUBMITTED_EMAIL = Email(
    subject=None,
    body="""
        <p>Hi {name},</p>

        <p>
        I can submit that for you. Thank you for letting us know.
        </p>

        <p>
        This will be processed at the next board meeting. I will send a confirmation
        of the board's decision after this occurs.
        </p>

        <p><strong>Next steps:</strong></p>

        <ol>
        <li>
            Please cancel your auto pay, if you are using it.
        </li>
        <li>
            Remove all belongings from the lab, including items in your locker and in
            short term storage.
        </li>
        <li>
            Ensure your due payments are up to date so your request can be accepted.
        </li>
        </ol>

        <p>
            If there are any issues with your hiatus you’ll be asked to pay for the month,
            but until then you’re fine to keep your payment cancelled.
        </p>

        <p>
            If you have any questions, please let me know.
        </p>
    """
)


HIATUS_APPROVED_EMAIL= Email(
    subject=None,
    body="""
            <p>Hi {name},</p>

            <p>
                I’m writing to confirm that your request for a hiatus has been approved.
                Your hiatus will begin on <strong>{start_date}</strong> and end on
                <strong>{end_date}</strong>. During this time, you will not be responsible for
                any membership activities or fees. However, please note that you will still
                retain your voting rights and are expected to attend general meetings.
            </p>

            <p>
                Before the start of your hiatus, <strong>please remove all of your belongings</strong> from the lab,
                including:
            </p>

            <ul>
                <li>All items from your locker, and the label on the outside</li>
                <li>Any items in storage, free and paid</li>
                <li>Items stored in the paint cabinet</li>
                <li>Laser/sheet goods storage</li>
            </ul>

            <p>
                If you have any questions or need further assistance, please feel free to
                reach out. We look forward to welcoming you back after your hiatus.
            </p>

            <p>Take care,</p>
        """
)


WITHDRAWAL_EMAIL = Email(
    subject=None,
    body="""
            <p>Hi {name},</p>

            <p>Your withdrawal will become official on {date}</p>

            <p>
            Before this date, <strong>please remove all of your belongings</strong> from the lab,
            including:
            </p>

            <ul>
            <li>All items from your locker, and the label on the outside</li>
            <li>Any items in storage, free and paid</li>
            <li>Items stored in the paint cabinet</li>
            <li>Laser/sheet goods storage</li>
            </ul>

            <p>
            Anything left behind after this date will become property of the lab.
            </p>

            <p>
            I hope to see you again in the future.
            </p>
        """
)

REJECTION_EMAIL = Email(
    subject="Kwartzlab Rejection",
    body="""
        <p>Hi {name},</p>

        <p>
            Thank you for your interest in joining KwartzLab. After careful review and a
            collective decision by our team, we have decided not to move forward with your
            membership application.
        </p>

        <p>
            We appreciate your time and wish you the best in your future endeavors.
        </p>
        """
)
