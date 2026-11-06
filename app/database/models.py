
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Date,
    DateTime,
    Integer,
    Float,
    Numeric,
    ForeignKey,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# 1. AGENT RETAILERS
class AgentRetailers(Base):
    __tablename__ = "Agent_Retailers"

    Agent_ID: Mapped[str] = mapped_column(String(100), primary_key=True)
    Agent_name: Mapped[Optional[str]] = mapped_column(String(255))
    Agent_location: Mapped[Optional[str]] = mapped_column(String(255))
    City: Mapped[Optional[str]] = mapped_column(String(100))
    Agent_reg_date: Mapped[Optional[object]] = mapped_column(DateTime)
    Agent_status: Mapped[Optional[str]] = mapped_column(String(50))
    Agent_type: Mapped[Optional[str]] = mapped_column(String(100))


# 2. CUSTOMERS
class Customers(Base):
    __tablename__ = "customers"

    Customer_ID: Mapped[str] = mapped_column(String(100), primary_key=True)
    Reg_Date: Mapped[Optional[object]] = mapped_column(DateTime)
    Acc_Status: Mapped[Optional[str]] = mapped_column(String(50))
    City: Mapped[Optional[str]] = mapped_column(String(100))
    Customer_segment: Mapped[Optional[str]] = mapped_column(String(100))


# 3. DEVICES
class Devices(Base):
    __tablename__ = "Devices"

    Device_ID: Mapped[str] = mapped_column(String(100), primary_key=True)
    Device_type: Mapped[Optional[str]] = mapped_column(String(100))
    Device_OS: Mapped[Optional[str]] = mapped_column(String(100))
    Device_model: Mapped[Optional[str]] = mapped_column(String(150))
    Device_first_seen: Mapped[Optional[object]] = mapped_column(DateTime)
    Device_last_seen: Mapped[Optional[object]] = mapped_column(DateTime)
    Device_status: Mapped[Optional[str]] = mapped_column(String(50))


# 4. NETWORK SESSIONS
class NetworkSessions(Base):
    __tablename__ = "Network_Sessions"

    Session_ID: Mapped[str] = mapped_column(String(100), primary_key=True)

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Device_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Devices.Device_ID"),
        nullable=False,
        index=True
    )

    Session_start: Mapped[Optional[object]] = mapped_column(DateTime)
    Session_end: Mapped[Optional[object]] = mapped_column(DateTime)
    IP_address: Mapped[Optional[str]] = mapped_column(String(100))
    Latitude: Mapped[Optional[float]] = mapped_column(Float)
    Longitude: Mapped[Optional[float]] = mapped_column(Float)
    City: Mapped[Optional[str]] = mapped_column(String(100))
    Network_type: Mapped[Optional[str]] = mapped_column(String(100))
    ISP: Mapped[Optional[str]] = mapped_column(String(150))

    __table_args__ = (
        Index("ix_sessions_customer_start", "Customer_ID", "Session_start"),
    )


# 5. AUTHENTICATION LOGS
class AuthenticationLogs(Base):
    __tablename__ = "Authentication_Logs"

    Auth_event_ID: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Device_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Devices.Device_ID"),
        nullable=False,
        index=True
    )

    Session_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Network_Sessions.Session_ID"),
        nullable=False,
        index=True
    )

    Event_timestamp: Mapped[Optional[object]] = mapped_column(DateTime)
    Event_type: Mapped[Optional[str]] = mapped_column(String(100))
    Auth_method: Mapped[Optional[str]] = mapped_column(String(100))
    Result: Mapped[Optional[str]] = mapped_column(String(50))
    Failure_reason: Mapped[Optional[str]] = mapped_column(String(255))
    Attempt_count: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        Index(
            "ix_auth_customer_timestamp",
            "Customer_ID",
            "Event_timestamp"
        ),
    )


# 6. BENEFICIARIES
class Beneficiaries(Base):
    __tablename__ = "Beneficiaries"

    Beneficiary_ID: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Beneficiary_customer_ID: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=True,
        index=True
    )

    Beneficiary_account: Mapped[Optional[str]] = mapped_column(String(150))
    Beneficiary_type: Mapped[Optional[str]] = mapped_column(String(100))
    Beneficiary_added_time: Mapped[Optional[object]] = mapped_column(DateTime)
    Beneficiary_status: Mapped[Optional[str]] = mapped_column(String(50))


# 7. TRANSACTIONS
class Transactions(Base):
    __tablename__ = "Transactions"

    Transaction_ID: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Session_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Network_Sessions.Session_ID"),
        nullable=False,
        index=True
    )

    Beneficiary_ID: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("Beneficiaries.Beneficiary_ID"),
        nullable=True,
        index=True
    )

    Agent_ID: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("Agent_Retailers.Agent_ID"),
        nullable=True,
        index=True
    )

    # Receiver_ID is deliberately not a foreign key.
    # Some receiver identifiers are outside the available customer records.
    Receiver_ID: Mapped[Optional[str]] = mapped_column(String(100))

    Timestamp: Mapped[Optional[object]] = mapped_column(DateTime)
    Transaction_Type: Mapped[Optional[str]] = mapped_column(String(100))
    Amount: Mapped[Optional[object]] = mapped_column(Numeric(18, 2))
    Currency: Mapped[Optional[str]] = mapped_column(String(20))
    Channel: Mapped[Optional[str]] = mapped_column(String(100))
    Transaction_status: Mapped[Optional[str]] = mapped_column(String(50))
    Sender_balance_before: Mapped[Optional[object]] = mapped_column(
        Numeric(18, 2)
    )
    Sender_balance_after: Mapped[Optional[object]] = mapped_column(
        Numeric(18, 2)
    )

    __table_args__ = (
        Index(
            "ix_transactions_customer_timestamp",
            "Customer_ID",
            "Timestamp"
        ),
    )


# 8. BIOMETRIC LOGS
class BiometricLogs(Base):
    __tablename__ = "Biometric_Logs"

    Biometric_event_ID: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Transaction_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Transactions.Transaction_ID"),
        nullable=False,
        index=True
    )

    Agent_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Agent_Retailers.Agent_ID"),
        nullable=False,
        index=True
    )

    Event_Timestamp: Mapped[Optional[object]] = mapped_column(DateTime)
    Biometric_type: Mapped[Optional[str]] = mapped_column(String(100))
    Biometric_required: Mapped[Optional[str]] = mapped_column(String(30))
    Attempt_count: Mapped[Optional[int]] = mapped_column(Integer)
    Failed_attempts: Mapped[Optional[int]] = mapped_column(Integer)
    Result: Mapped[Optional[str]] = mapped_column(String(50))


# 9. FRAUD ALERTS
class FraudAlerts(Base):
    __tablename__ = "Fraud_Alerts"

    Alert_ID: Mapped[str] = mapped_column(String(100), primary_key=True)

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Transaction_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Transactions.Transaction_ID"),
        nullable=False,
        index=True
    )

    Alert_timestamp: Mapped[Optional[object]] = mapped_column(DateTime)
    Alert_type: Mapped[Optional[str]] = mapped_column(String(100))
    Criticality_score: Mapped[Optional[object]] = mapped_column(
        Numeric(8, 4)
    )
    Criticality_level: Mapped[Optional[str]] = mapped_column(String(50))
    Alert_source: Mapped[Optional[str]] = mapped_column(String(100))
    Alert_status: Mapped[Optional[str]] = mapped_column(String(50))


# 10. COMPLAINTS
class Complaints(Base):
    __tablename__ = "Complaints"

    Complaint_ID: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Transaction_ID: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("Transactions.Transaction_ID"),
        nullable=True,
        index=True
    )

    Complaint_timestamp: Mapped[Optional[object]] = mapped_column(DateTime)
    Complaint_Type: Mapped[Optional[str]] = mapped_column(String(100))
    Complaint_channel: Mapped[Optional[str]] = mapped_column(String(100))
    Complaint_description: Mapped[Optional[str]] = mapped_column(Text)
    Complaint_status: Mapped[Optional[str]] = mapped_column(String(50))


# 11. CASES
class Cases(Base):
    __tablename__ = "Cases"

    Case_ID: Mapped[str] = mapped_column(String(100), primary_key=True)

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Alert_ID: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("Fraud_Alerts.Alert_ID"),
        nullable=True
    )

    Complaint_ID: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("Complaints.Complaint_ID"),
        nullable=True
    )

    Case_created_timestamp: Mapped[Optional[object]] = mapped_column(
        DateTime
    )

    Case_source: Mapped[Optional[str]] = mapped_column(String(50))
    Case_status: Mapped[Optional[str]] = mapped_column(String(50))
    Case_priority: Mapped[Optional[str]] = mapped_column(String(50))

    __table_args__ = (
        CheckConstraint(
            """
            (Alert_ID IS NOT NULL AND Complaint_ID IS NULL)
            OR
            (Alert_ID IS NULL AND Complaint_ID IS NOT NULL)
            """,
            name="ck_cases_exactly_one_source"
        ),
    )


# 12. CUSTOMER DEVICE
class CustomerDevice(Base):
    __tablename__ = "Customer_Device"

    Customer_Device_ID: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Device_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("Devices.Device_ID"),
        nullable=False,
        index=True
    )

    First_seen: Mapped[Optional[object]] = mapped_column(DateTime)
    Last_seen: Mapped[Optional[object]] = mapped_column(DateTime)
    Link_status: Mapped[Optional[str]] = mapped_column(String(50))


# 13. KYC RECORDS
class KYCRecords(Base):
    __tablename__ = "KYC_records"

    KYC_ID: Mapped[str] = mapped_column(String(100), primary_key=True)

    Customer_ID: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("customers.Customer_ID"),
        nullable=False,
        index=True
    )

    Full_name: Mapped[Optional[str]] = mapped_column(String(255))
    CNIC: Mapped[Optional[str]] = mapped_column(String(50))
    DOB: Mapped[Optional[object]] = mapped_column(Date)
    Guardian_Name: Mapped[Optional[str]] = mapped_column(String(255))
    Reg_Mobile: Mapped[Optional[str]] = mapped_column(String(50))
    Reg_Address: Mapped[Optional[str]] = mapped_column(Text)
    City: Mapped[Optional[str]] = mapped_column(String(100))
    KYC_Reg_Date: Mapped[Optional[object]] = mapped_column(DateTime)
    KYC_status: Mapped[Optional[str]] = mapped_column(String(50))
    KYC_last_updated_date: Mapped[Optional[object]] = mapped_column(
        DateTime
    )
