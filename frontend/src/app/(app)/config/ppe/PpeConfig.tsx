"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Forbidden, PageHeader } from "@/components/shell/AppShell";
import { Alert } from "@/components/ui/Alert";
import { PageLoading } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { can, PERMISSIONS, useMe } from "@/lib/auth";

import { ppeKey, type PpeConfig as PpeConfigData } from "../_shared/types";
import { AddClassDialog, ClassRegistry } from "./ClassRegistry";
import { AddPpeDialog, PpeItemsPanel } from "./PpeItemsPanel";

export function PpeConfig() {
  const { data: me } = useMe();
  const allowed = can(me, PERMISSIONS.configPpe);
  const config = useQuery({ queryKey: ppeKey, queryFn: () => api<PpeConfigData>("/config/ppe"), enabled: allowed });
  const [addingPpe, setAddingPpe] = useState(false);
  const [addingClass, setAddingClass] = useState(false);

  if (!allowed) return <Forbidden />;
  if (config.isPending) return <PageLoading />;
  if (config.isError) return <Alert tone="critical">{config.error.message}</Alert>;

  const { ppe_items, classes, active_model } = config.data;
  const notInModel = classes.filter((c) => c.enabled && !c.in_active_model);

  return (
    <>
      <PageHeader
        eyebrow="Configuration"
        title="PPE & classes"
        description="The PPE types areas can require, and how confident the model must be before a detection counts. Changes reach live detection within about 30 seconds."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setAddingPpe(true)}>
            <Plus className="size-4" aria-hidden /> Add PPE type
          </button>
        }
      />

      <div className="grid items-start gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <section className="panel" aria-labelledby="ppe-items-head">
          <div className="border-b border-line p-4">
            <h2 id="ppe-items-head" className="rule-head">PPE types</h2>
            <p className="mt-1.5 text-xs text-ink-3">
              Turning a type off stops it raising violations everywhere, without changing each camera.
            </p>
          </div>
          <PpeItemsPanel items={ppe_items} />
          <div className="border-t border-line p-4 text-xs text-ink-2">
            A new PPE type is only detected once examples have been{" "}
            <Link href="/annotate" className="font-medium text-accent-700 hover:underline">
              annotated
            </Link>{" "}
            and the model{" "}
            <Link href="/training" className="font-medium text-accent-700 hover:underline">
              retrained
            </Link>
            .
          </div>
        </section>

        <section className="panel min-w-0" aria-labelledby="classes-head">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line p-4">
            <div className="max-w-2xl">
              <h2 id="classes-head" className="rule-head">Detection classes</h2>
              <p className="mt-1.5 text-xs text-ink-3">
                A detection only counts when the model&apos;s confidence reaches the class threshold. Raising it means fewer
                false alarms but more missed violations; lowering it does the opposite.
                {active_model && ` Active model: ${active_model.name}.`}
              </p>
            </div>
            <button type="button" className="btn btn-sm" onClick={() => setAddingClass(true)}>
              <Plus className="size-3.5" aria-hidden /> Add class
            </button>
          </div>
          {notInModel.length > 0 && (
            <div className="border-b border-line p-4">
              <Alert tone="warn">
                The active model can&apos;t output {notInModel.map((c) => c.name).join(", ")} yet. Annotate examples and retrain
                to start detecting {notInModel.length === 1 ? "it" : "them"}.
              </Alert>
            </div>
          )}
          <ClassRegistry classes={classes} ppeItems={ppe_items} />
        </section>
      </div>

      <AddPpeDialog open={addingPpe} onClose={() => setAddingPpe(false)} />
      <AddClassDialog open={addingClass} ppeItems={ppe_items} onClose={() => setAddingClass(false)} />
    </>
  );
}
